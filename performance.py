#!/usr/bin/env python3
import asyncio
import json
import os
import shutil

import pandas as pd

from datetime import datetime, timedelta, timezone
from enum import Enum
import pathlib
import sys

from yapapi.contrib.strategy import ProviderFilter
from yapapi.script import Script
from yapapi.golem import Golem
from yapapi.payload import vm
from yapapi.services import Service
from yapapi.strategy import LeastExpensiveLinearPayuMS
from yapapi.utils import logger

examples_dir = pathlib.Path(__file__).resolve().parent.parent
sys.path.append(str(examples_dir))

from utils import (
    build_parser,
    TEXT_COLOR_CYAN,
    TEXT_COLOR_DEFAULT,
    run_golem_example,
    print_env_info,
    TEXT_COLOR_GREEN,
)

# the timeout after we commission our service instances
# before we abort this script
STARTING_TIMEOUT = timedelta(minutes=5)

# additional expiration margin to allow providers to take our offer,
# as providers typically won't take offers that expire sooner than 5 minutes in the future
EXPIRATION_MARGIN = timedelta(minutes=5)

TEMP_PATH = ".tmp"

lock = asyncio.Lock()

# TODO: Get rid of globals
computation_state_server = {}
computation_state_client = {}
completion_state = {}
ip_provider_id = {}
network_addresses = []
transfer_list = []
vpn_ping_list = []
vpn_transfer_list = []


class State(Enum):
    IDLE = 0
    COMPUTING = 1


class PerformanceScript(Script):
    async def _before(self):
        self.before = datetime.now().timestamp()
        await super()._before()

    async def _after(self):
        self.after = datetime.now().timestamp()
        await super()._after()

    def __init__(self, script: Script):
        self.before = None
        self.after = None
        self.timeout = script.timeout
        self.wait_for_results = script.wait_for_results
        self._ctx = script._ctx
        self._commands = script._commands
        self._id: int = script._id

    def calculate_transfer(self, bts):
        dt = self.after - self.before
        return (bts / dt).__round__(3)


class PerformanceService(Service):
    def __init__(
        self,
        transfer: bool,
        transfer_file_size: int,
        vpn_ping: bool,
        ping_count: int,
        vpn_transfer: bool,
    ):
        super().__init__()
        self.transfer_file_size = transfer_file_size
        self.transfer = transfer
        self.vpn_ping = vpn_ping
        self.ping_count = ping_count
        self.vpn_transfer = vpn_transfer

    @staticmethod
    async def get_payload():
        return await vm.repo(
            image_hash="6aa7ef45d0f4c91e147a01c2f311c63bfeb742ea6743ae8e407cd202",
            min_mem_gib=1.0,
            min_storage_gib=0.5,
        )

    async def start(self):
        async for script in super().start():
            yield script
        script = self._ctx.new_script()
        script.run("/bin/bash", "-c", f"iperf3 -s -D")

        yield script
        server_ip = self.network_node.ip
        ip_provider_id[server_ip] = self.provider_id
        computation_state_server[server_ip] = State.IDLE
        computation_state_client[server_ip] = State.IDLE

        if self.transfer:

            async def dummy(v):
                pass

            await lock.acquire()
            value = bytes(self.transfer_file_size * 1024 * 1024)
            path = "/golem/output/dummy"
            logger.info(f"Provider: {self.provider_id}. 🚀 Starting transfer test. ")
            script = self._ctx.new_script()
            script.upload_bytes(value, path)
            script = PerformanceScript(script)
            yield script
            upload = script.calculate_transfer(self.transfer_file_size)

            script = self._ctx.new_script()
            script.download_bytes(path, on_download=dummy)
            script = PerformanceScript(script)
            yield script

            download = script.calculate_transfer(self.transfer_file_size)
            logger.info(
                f"Provider: {self.provider_id}. 🎉 Finished transfer test: ⬆ upload {upload} MByte/s, ⬇ download {download} MByte/s"
            )
            transfer_list.append(
                {
                    "provider_id": self.provider_id,
                    "upload_mb_s": upload,
                    "download_mb_s": download,
                }
            )

            lock.release()

        network_addresses.append(server_ip)

    async def run(self):
        global computation_state_client
        global computation_state_server
        global completion_state

        while len(network_addresses) < len(self.cluster.instances):
            await asyncio.sleep(1)

        client_ip = self.network_node.ip
        neighbour_count = len(network_addresses) - 1
        completion_state[client_ip] = set()

        logger.info(f"{self.provider_id}: 🏃 running")
        await asyncio.sleep(5)

        while len(completion_state[client_ip]) < neighbour_count:

            for server_ip in network_addresses:
                if server_ip == client_ip:
                    continue
                elif server_ip in completion_state[client_ip]:
                    continue
                elif server_ip not in computation_state_server:
                    continue
                await lock.acquire()
                if (
                    computation_state_server[server_ip] != State.IDLE
                    or computation_state_client[server_ip] != State.IDLE
                    or computation_state_server[client_ip] != State.IDLE
                ):
                    lock.release()
                    await asyncio.sleep(1)
                    continue

                computation_state_server[server_ip] = State.COMPUTING
                computation_state_client[client_ip] = State.COMPUTING
                lock.release()

                await asyncio.sleep(1)

                logger.info(f"{self.provider_id} 🔄 computing on {ip_provider_id[server_ip]}")

                try:
                    if self.vpn_ping:
                        logger.info(
                            f"Starting VPN ping test 👀. {self.provider_id} sending {self.ping_count} pings to {ip_provider_id[server_ip]}"
                        )
                        script = self._ctx.new_script()
                        future_result = script.run(
                            "/bin/bash",
                            "-c",
                            f'ping -c {self.ping_count} {server_ip} | pingparsing - | jq \'del(.destination) | {{"server":"{ip_provider_id[server_ip]}"}} + .| {{"client":"{self.provider_id}"}} + .\'',
                        )
                        yield script

                        result = (await future_result).stdout
                        data = json.loads(result)
                        append_vpn_ping_list(
                            self.provider_id,
                            ip_provider_id[server_ip],
                            data["packet_loss_rate"],
                            data["rtt_min"],
                            data["rtt_avg"],
                            data["rtt_max"],
                        )

                        logger.info(
                            f"Finished VPN ping test 🎉. Average ping sent from {self.provider_id} to {ip_provider_id[server_ip]} is {data['rtt_avg']} ms"
                        )

                except Exception as error:
                    logger.info(
                        f" 💀💀💀 VPN ping test 💀💀💀 error: {error}. Client: {self.provider_id}, server: {ip_provider_id[server_ip]}."
                    )

                try:
                    if self.vpn_transfer:
                        logger.info(
                            f"Starting VPN transfer test 🚌. Client: {self.provider_id}, server: {ip_provider_id[server_ip]}"
                        )
                        output_file_vpn_transfer = (
                            f"vpn_transfer_client_{client_ip}_to_server_{server_ip}_logs.json"
                        )
                        script = self._ctx.new_script()
                        script.run(
                            "/bin/bash",
                            "-c",
                            f'iperf3 -c {server_ip} -f M -w 60000 -J | jq \'{{"server":"{ip_provider_id[server_ip]}"}} + .| {{"client":"{self.provider_id}"}} + .\' > /golem/output/{output_file_vpn_transfer}',
                        )
                        yield script

                        # TODO: Change for stdout to avoid downloading file
                        script = self._ctx.new_script()
                        dt = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
                        output_file_vpn_transfer_with_date = (
                            f"{TEMP_PATH}/{dt}_{output_file_vpn_transfer}"
                        )
                        script.download_file(
                            f"/golem/output/{output_file_vpn_transfer}",
                            f"{output_file_vpn_transfer_with_date}",
                        )
                        yield script

                        with open(f"{output_file_vpn_transfer_with_date}") as file:
                            f = file.read()

                        data = json.loads(f)

                        try:
                            bandwidth_sender_mb_s = (
                                (data["end"]["sum_sent"]["bits_per_second"]) / (8 * 1024 * 1024)
                            ).__round__(3)
                            bandwidth_receiver_mb_s = (
                                (data["end"]["sum_received"]["bits_per_second"]) / (8 * 1024 * 1024)
                            ).__round__(3)
                        except Exception:
                            error = data["error"]
                            raise Exception(error)

                        append_vpn_transfer_list(
                            self.provider_id,
                            ip_provider_id[server_ip],
                            bandwidth_sender_mb_s,
                            bandwidth_receiver_mb_s,
                        )

                        logger.info(
                            f"Finished VPN transfer test 🎉. Client: {self.provider_id}, server: {ip_provider_id[server_ip]}. Bandwidth: ⬆ sender {bandwidth_sender_mb_s} MByte/s, ⬇ receiver {bandwidth_receiver_mb_s} MByte/s"
                        )
                except Exception as error:
                    logger.info(
                        f" 💀💀💀 VPN transfer test 💀💀💀 error: {error}. Client: {self.provider_id}, server: {ip_provider_id[server_ip]}."
                    )
                    append_vpn_transfer_list(self.provider_id, ip_provider_id[server_ip])

                completion_state[client_ip].add(server_ip)
                logger.info(f"{self.provider_id} ✅ finished on {ip_provider_id[server_ip]}")

                await lock.acquire()
                computation_state_server[server_ip] = State.IDLE
                computation_state_client[client_ip] = State.IDLE
                lock.release()

            await asyncio.sleep(1)

        logger.info(f"{self.provider_id}: 🎉 finished computing")

        # keep running - nodes may want to compute on this node
        while len(completion_state) < neighbour_count or not all(
            [len(c) == neighbour_count for c in completion_state.values()]
        ):
            await asyncio.sleep(1)

        logger.info(f"{self.provider_id}: 🚪 exiting")

    async def reset(self):
        pass


def append_vpn_transfer_list(
    client, server, bandwidth_sender_mb_s=None, bandwidth_receiver_mb_s=None
):
    vpn_transfer_list.append(
        {
            "client": client,
            "server": server,
            "p2p_connection": "",
            "bandwidth_sender_mb_s": bandwidth_sender_mb_s,
            "bandwidth_receiver_mb_s": bandwidth_receiver_mb_s,
        }
    )


def append_vpn_ping_list(
    client, server, packet_loss_percentage, rtt_min_ms, rtt_avg_ms, rtt_max_ms
):
    vpn_ping_list.append(
        {
            "client": client,
            "server": server,
            "p2p_connection": "",
            "packet_loss_percentage": packet_loss_percentage,
            "rtt_min_ms": rtt_min_ms,
            "rtt_avg_ms": rtt_avg_ms,
            "rtt_max_ms": rtt_max_ms,
        }
    )


async def main(
    subnet_tag,
    payment_driver,
    payment_network,
    num_instances,
    running_time,
    transfer,
    transfer_file_size,
    vpn_ping,
    ping_count,
    vpn_transfer,
    download_json,
    instances=None,
):
    strategy = LeastExpensiveLinearPayuMS()

    with open("providers_list.json") as file:
        providers = json.load(file)

    if providers:
        if num_instances > len(providers):
            raise Exception(
                f"Trying to test {num_instances} nodes, but only {len(providers)} providers ID provided in providers_list.json file"
            )
        # Take only first n provider_id from file
        first_n_elements = providers[:num_instances]
        strategy = ProviderFilter(strategy, lambda provider_id: provider_id in first_n_elements)

    async with Golem(
        budget=1.0,
        subnet_tag=subnet_tag,
        payment_driver=payment_driver,
        payment_network=payment_network,
        strategy=strategy,
    ) as golem:
        print_env_info(golem)

        global network_addresses

        network = await golem.create_network("192.168.0.1/24")
        os.makedirs(TEMP_PATH, exist_ok=True)

        cluster = await golem.run_service(
            PerformanceService,
            instance_params=[
                {
                    "transfer": transfer,
                    "transfer_file_size": transfer_file_size,
                    "vpn_ping": vpn_ping,
                    "ping_count": ping_count,
                    "vpn_transfer": vpn_transfer,
                }
                for i in range(num_instances)
            ],
            network=network,
            num_instances=num_instances,
            expiration=datetime.now(timezone.utc)
            + STARTING_TIMEOUT
            + EXPIRATION_MARGIN
            + timedelta(seconds=running_time),
        )

        start_time = datetime.now()

        while (
            datetime.now() < start_time + timedelta(seconds=running_time)
            and len(completion_state) < num_instances
            or not all([len(c) == num_instances - 1 for c in completion_state.values()])
        ):
            try:
                await asyncio.sleep(10)
            except (KeyboardInterrupt, asyncio.CancelledError):
                break

        cluster.stop()

        if transfer_list:
            transfer_result_json = json.dumps(sorted(transfer_list, key=lambda x: x["provider_id"]))

            print(f"{TEXT_COLOR_CYAN}-------------------------------------------------------")
            print(
                f"Transfer test with file size: {TEXT_COLOR_GREEN}{transfer_file_size} MB{TEXT_COLOR_CYAN}"
            )
            result = pd.read_json(transfer_result_json, orient="records")
            print(f"{result}{TEXT_COLOR_DEFAULT}")

            if download_json:
                dt = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
                with open(f"transfer_test_result_{transfer_file_size}MB_{dt}.json", "a+") as file:
                    file.write(transfer_result_json)

        if vpn_ping_list:
            vpn_ping_result_json = json.dumps(sorted(vpn_ping_list, key=lambda x: x["client"]))

            print(f"{TEXT_COLOR_CYAN}-------------------------------------------------------")
            print("VPN ping test between providers")
            result = pd.read_json(vpn_ping_result_json, orient="records")
            print(f"{result}{TEXT_COLOR_DEFAULT}")

            if download_json:
                dt = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
                with open(f"vpn_ping_test_result_{ping_count}_pings_{dt}.json", "a+") as file:
                    file.write(vpn_ping_result_json)

        if vpn_transfer_list:
            vpn_transfer_result_json = json.dumps(
                sorted(vpn_transfer_list, key=lambda x: x["client"])
            )

            print(f"{TEXT_COLOR_CYAN}-------------------------------------------------------")
            print("VPN transfer test between providers")
            result = pd.read_json(vpn_transfer_result_json, orient="records")
            print(f"{result}{TEXT_COLOR_DEFAULT}")

            if download_json:
                dt = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
                with open(f"vpn_transfer_test_result_{dt}.json", "a+") as file:
                    file.write(vpn_transfer_result_json)

        shutil.rmtree(TEMP_PATH)


if __name__ == "__main__":
    parser = build_parser("NET measurement tool")
    parser.add_argument(
        "--num-instances",
        type=int,
        default=2,
        help="The number of nodes for test",
    )
    parser.add_argument(
        "--running-time",
        default=1200,
        type=int,
        help=(
            "Option to set time the instance run before the cluster is stopped"
            "(in seconds, default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--transfer",
        action="store_true",
        help="Enable GFTP transfer test",
    )
    parser.add_argument(
        "--transfer-file-size",
        default=10,
        type=int,
        help="Sets transferred file size (in Mbytes, default: %(default)MB)",
    )
    parser.add_argument(
        "--vpn-ping",
        action="store_true",
        help="Option to disable test",
    )
    parser.add_argument(
        "--ping-count",
        default=10,
        type=int,
        help="Specifies the number of ping packets to send",
    )
    parser.add_argument(
        "--vpn-transfer",
        action="store_true",
        help="Enable VPN transfer test",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Download results as json files",
    )
    now = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    parser.set_defaults(log_file=f"ya-perf-{now}.log")
    args = parser.parse_args()

    run_golem_example(
        main(
            subnet_tag=args.subnet_tag,
            payment_driver=args.payment_driver,
            payment_network=args.payment_network,
            num_instances=args.num_instances,
            running_time=args.running_time,
            transfer=args.transfer,
            transfer_file_size=args.transfer_file_size,
            vpn_ping=args.vpn_ping,
            ping_count=args.ping_count,
            vpn_transfer=args.vpn_transfer,
            download_json=args.json,
        ),
        log_file=args.log_file,
    )
