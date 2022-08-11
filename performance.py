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
ip_provider_name = {}
network_addresses = []
transfer_list = []
vpn_ping_list = []
vpn_transfer_list = []
cmd_output_list = []
mapping = {}
closed = []


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
        scp: bool,
        scp_transfer_file_size: int,
        cmd_output_count: int,
        cmd_output_size: int,
    ):
        super().__init__()
        self.transfer_file_size = transfer_file_size
        self.transfer = transfer
        self.vpn_ping = vpn_ping
        self.ping_count = ping_count
        self.vpn_transfer = vpn_transfer
        self.scp = scp
        self.scp_transfer_file_size = scp_transfer_file_size
        self.cmd_output_count = cmd_output_count
        self.cmd_output_size = cmd_output_size

    @staticmethod
    async def get_payload():
        return await vm.repo(
            image_hash="3f521a6f14ffb4564c656cfc73fed7bf2dc2b146a25877af9f13c88d",
            min_mem_gib=1.0,
            min_storage_gib=0.5,
        )

    async def start(self):

        try:
            async for script in super().start():
                yield script
            script = self._ctx.new_script()
            script.run("/bin/bash", "-c", "iperf3 -s -D")
            script.run("/bin/bash", "-c", "/usr/sbin/sshd")
            if self.scp:
                script.run(
                    "/bin/bash",
                    "-c",
                    f"truncate -s {self.scp_transfer_file_size}M /golem/dummy.dat",
                )
            yield script
        except Exception as error:
            logger.info(
                f" 💀💀💀 Starting instance 💀💀💀 error: {error}. Provider: {self.provider_name}."
            )

        server_ip = self.network_node.ip
        ip_provider_name[server_ip] = self.provider_name
        computation_state_server[server_ip] = State.IDLE
        computation_state_client[server_ip] = State.IDLE

        if self.transfer:

            async def dummy(v):
                pass

            async with lock:
                try:
                    value = bytes(self.transfer_file_size * 1024 * 1024)
                    path = "/golem/output/dummy"
                    logger.info(f"Provider: {self.provider_name}. 🚀 Starting transfer test. ")
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
                        f"Provider: {self.provider_name}. 🎉 Finished transfer test: ⬆ upload {upload} MByte/s, ⬇ download {download} MByte/s"
                    )
                    transfer_list.append(
                        {
                            "provider_name": self.provider_name,
                            "upload_mb_s": upload,
                            "download_mb_s": download,
                        }
                    )

                    network_addresses.append(server_ip)
                    mapping.update(
                        {
                            self.provider_id: self.provider_name,
                        }
                    )

                except Exception as error:
                    logger.info(
                        f" 💀💀💀 Transfer test 💀💀💀 error: {error}. Provider: {self.provider_name}."
                    )

        else:
            network_addresses.append(server_ip)
            mapping.update(
                {
                    self.provider_id: self.provider_name,
                }
            )

    async def run(self):
        global computation_state_client
        global computation_state_server
        global completion_state

        async with lock:
            while len(network_addresses) < (len(self.cluster.instances) - len(closed)):
                await asyncio.sleep(1)

        client_ip = self.network_node.ip
        completion_state[client_ip] = set()

        logger.info(f"{self.provider_name}: 🏃 running")

        while True:
            async with lock:
                if computation_state_server[client_ip] == State.IDLE:
                    computation_state_client[client_ip] = State.COMPUTING
                    break
            await asyncio.sleep(1)

        try:
            if self.cmd_output_count:
                logger.info(
                    f"Starting command output test {self.cmd_output_size} B x {self.cmd_output_count} 🚌. Provider: {self.provider_name}"
                )

                for _ in range(self.cmd_output_count):
                    script = self._ctx.new_script()
                    future_result = script.run(
                        "/bin/bash",
                        "-c",
                        f"tr -dc A-Za-z0-9 < /dev/urandom | head -c {self.cmd_output_size}",
                    )

                    yield script
                    await future_result

                logger.info(f"Finished command output test 🎉. Provider: {self.provider_name}.")
                append_cmd_output_list(self.provider_name, True)

        except Exception as error:
            append_cmd_output_list(self.provider_name, False)
            logger.error(
                f"💀💀💀 Command output test 💀💀💀 error: {error}. Provider: {self.provider_name}."
            )

        finally:
            async with lock:
                computation_state_client[client_ip] = State.IDLE

        await asyncio.sleep(5)

        while len(completion_state[client_ip]) < ((len(network_addresses) - 1) - len(closed)):
            for server_ip in network_addresses:
                if ip_provider_name[server_ip] in closed:
                    break
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

                logger.info(f"{self.provider_name} 🔄 computing on {ip_provider_name[server_ip]}")

                if self.vpn_ping:
                    try:
                        logger.info(
                            f"Starting VPN ping test 👀. {self.provider_name} sending {self.ping_count} pings to {ip_provider_name[server_ip]}"
                        )
                        script = self._ctx.new_script()
                        future_result = script.run(
                            "/bin/bash",
                            "-c",
                            f'ping -c {self.ping_count} {server_ip} | pingparsing - | jq \'del(.destination) | {{"server":"{ip_provider_name[server_ip]}"}} + .| {{"client":"{self.provider_name}"}} + .\'',
                        )
                        yield script

                        result = (await future_result).stdout
                        data = json.loads(result)
                        append_vpn_ping_list(
                            self.provider_name,
                            ip_provider_name[server_ip],
                            data["packet_loss_rate"],
                            data["rtt_min"],
                            data["rtt_avg"],
                            data["rtt_max"],
                        )

                        logger.info(
                            f"Finished VPN ping test 🎉. Average ping sent from {self.provider_name} to {ip_provider_name[server_ip]} is {data['rtt_avg']} ms"
                        )

                    except Exception as error:
                        logger.info(
                            f"💀💀💀 VPN ping test 💀💀💀 error: {error}. Client: {self.provider_name}, server: {ip_provider_name[server_ip]}"
                        )

                if self.vpn_transfer:
                    logger.info(
                        f"Starting VPN transfer test 🚌. Client: {self.provider_name}, server: {ip_provider_name[server_ip]}"
                    )

                    if not self.scp:
                        try:
                            output_file_vpn_transfer = (
                                f"vpn_transfer_client_{client_ip}_to_server_{server_ip}_logs.json"
                            )

                            script = self._ctx.new_script()
                            script.run(
                                "/bin/bash",
                                "-c",
                                f'iperf3 -c {server_ip} -f M -w 60000 -J | jq \'{{"server":"{ip_provider_name[server_ip]}"}} + .| {{"client":"{self.provider_id}"}} + .\' > /golem/output/{output_file_vpn_transfer}',
                            )

                            yield script

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
                                    (data["end"]["sum_received"]["bits_per_second"])
                                    / (8 * 1024 * 1024)
                                ).__round__(3)

                                append_vpn_transfer_list(
                                    self.provider_name,
                                    ip_provider_name[server_ip],
                                    bandwidth_sender_mb_s,
                                    bandwidth_receiver_mb_s,
                                )

                                logger.info(
                                    f"Finished VPN transfer test 🎉. Client: {self.provider_name}, server: {ip_provider_name[server_ip]}. Bandwidth: ⬆ sender {bandwidth_sender_mb_s} MByte/s, ⬇ receiver {bandwidth_receiver_mb_s} MByte/s"
                                )

                            except Exception:
                                error = data["error"]
                                append_vpn_transfer_list(
                                    self.provider_name, ip_provider_name[server_ip]
                                )
                                logger.info(
                                    f"💀💀💀 VPN transfer test 💀💀💀 error: {error}. Client: {self.provider_name}, server: {ip_provider_name[server_ip]}"
                                )

                        except Exception as error:
                            append_vpn_transfer_list(
                                self.provider_name, ip_provider_name[server_ip]
                            )
                            logger.info(
                                f"💀💀💀 VPN transfer test 💀💀💀 error: {error}. Client: {self.provider_name}, server: {ip_provider_name[server_ip]}"
                            )

                    else:
                        try:
                            script = self._ctx.new_script()
                            future_result = script.run(
                                "/bin/bash",
                                "-c",
                                f"scp -v /golem/dummy.dat root@{server_ip}:/golem/upload",
                            )

                            yield script

                            result = (await future_result).stderr

                            bandwidth_sender_mb_s = parse_scp_result_upload(result)

                            script = self._ctx.new_script()
                            future_result = script.run(
                                "/bin/bash",
                                "-c",
                                f"scp -v root@{server_ip}:/golem/dummy.dat /golem/download",
                            )
                            yield script
                            result = (await future_result).stderr
                            bandwidth_receiver_mb_s = parse_scp_result_download(result)

                            append_vpn_transfer_list(
                                self.provider_name,
                                ip_provider_name[server_ip],
                                bandwidth_sender_mb_s,
                                bandwidth_receiver_mb_s,
                            )

                            logger.info(
                                f"Finished VPN transfer test 🎉. Client: {self.provider_name}, server: {ip_provider_name[server_ip]}. Bandwidth: ⬆ sender {bandwidth_sender_mb_s} MByte/s, ⬇ receiver {bandwidth_receiver_mb_s} MByte/s"
                            )

                        except Exception as error:
                            append_vpn_transfer_list(
                                self.provider_name, ip_provider_name[server_ip]
                            )
                            logger.info(
                                f"💀💀💀 VPN transfer test 💀💀💀 error: {error}. Client: {self.provider_name}, server: {ip_provider_name[server_ip]}"
                            )

                completion_state[client_ip].add(server_ip)
                # logger.info(f"{self.provider_name} ✅ finished on {ip_provider_name[server_ip]}")
                # print(f"computation_state_server before final unlock: {computation_state_server}")
                # print(f"computation_state_client before final unlock: {computation_state_client}")

                await lock.acquire()
                computation_state_server[server_ip] = State.IDLE
                computation_state_client[client_ip] = State.IDLE
                lock.release()

                # print(f"computation_state_server after final unlock: {computation_state_server}")
                # print(f"computation_state_client after final unlock: {computation_state_client}")

            await asyncio.sleep(1)

        # keep running - nodes may want to compute on this node
        while len(completion_state) < ((len(network_addresses) - 1) - len(closed)) or not all(
            [len(c) == ((len(network_addresses) - 1) - len(closed)) for c in completion_state.values()]
        ):
            await asyncio.sleep(1)

        logger.info(f"{self.provider_name}: 🎉 finished computing")
        logger.info(f"{self.provider_name}: 🚪 exiting")

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


def append_cmd_output_list(client, success):
    cmd_output_list.append({"client": client, "success": success})


def parse_scp_result_upload(result) -> float:
    result = result.split("\n")
    result = result[-3]
    result = result.split("sent")
    result = result[-1]
    result = result.split(",")
    result = result[0]

    return (float(result) / (1024 * 1024)).__round__(3)


def parse_scp_result_download(result) -> float:
    result = result.split("\n")
    result = result[-3]
    result = result.split("received")
    result = result[-1]

    return (float(result) / (1024 * 1024)).__round__(3)


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
    scp,
    scp_transfer_file_size,
    cmd_output_count,
    cmd_output_size,
    download_json,
    output_dir,
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
        budget=20.0,
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
                    "scp": scp,
                    "scp_transfer_file_size": scp_transfer_file_size,
                    "cmd_output_count": cmd_output_count,
                    "cmd_output_size": cmd_output_size,
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

        # def event_consumer(event: "yapapi.events.AgreementTerminated"):
        #     provider_name = event.agreement.details.provider_node_info.name
        #     print(f"{provider_name} failed! Shame on you!")
        #     if provider_name in mapping.values():
        #         closed.append(provider_name)
        #
        # golem.add_event_consumer(event_consumer, ["AgreementTerminated"])

        start_time = datetime.now()

        while (
            datetime.now() < start_time + timedelta(seconds=running_time)
            and (len(completion_state) - len(closed)) < (num_instances - len(closed))
            or not all([(len(c) - len(closed)) == (num_instances - 1 - len(closed)) for c in completion_state.values()])
        ):
            try:
                await asyncio.sleep(10)
            except (KeyboardInterrupt, asyncio.CancelledError):
                break

        cluster.stop()

        save_path = ""
        if output_dir:
            if not os.path.exists(output_dir):
                os.mkdir(output_dir)
            save_path = output_dir

        if closed:
            print(closed)

        if mapping:
            mapping_json = json.dumps(mapping)
            print(f"{TEXT_COLOR_CYAN}-------------------------------------------------------")
            print("Nodes mapping")
            result = pd.DataFrame(mapping.items(), columns=["node_id", "node_name"])
            print(f"{result}{TEXT_COLOR_DEFAULT}")

            if download_json:
                dt = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
                file_name = f"nodes-map_{dt}.json"
                complete_name = os.path.join(save_path, file_name)

                with open(complete_name, "a+") as file:
                    file.write(mapping_json)

        if transfer_list:
            transfer_result_json = json.dumps(
                sorted(transfer_list, key=lambda x: x["provider_name"])
            )

            print(f"{TEXT_COLOR_CYAN}-------------------------------------------------------")
            print(
                f"Transfer test with file size: {TEXT_COLOR_GREEN}{transfer_file_size} MB{TEXT_COLOR_CYAN}"
            )
            result = pd.read_json(transfer_result_json, orient="records")
            print(f"{result}{TEXT_COLOR_DEFAULT}")

            if download_json:
                dt = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
                file_name = f"transfer_test_result_{transfer_file_size}MB_{dt}.json"
                complete_name = os.path.join(save_path, file_name)

                with open(complete_name, "a+") as file:
                    file.write(transfer_result_json)

        if vpn_ping_list:
            vpn_ping_result_json = json.dumps(sorted(vpn_ping_list, key=lambda x: x["client"]))

            print(f"{TEXT_COLOR_CYAN}-------------------------------------------------------")
            print("VPN ping test between providers")
            result = pd.read_json(vpn_ping_result_json, orient="records")
            print(f"{result}{TEXT_COLOR_DEFAULT}")

            if download_json:
                dt = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
                file_name = f"vpn_ping_test_result_{ping_count}_pings_{dt}.json"
                complete_name = os.path.join(save_path, file_name)

                with open(complete_name, "a+") as file:
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
                file_name = f"vpn_transfer_test_result_{dt}.json"
                complete_name = os.path.join(save_path, file_name)

                with open(complete_name, "a+") as file:
                    file.write(vpn_transfer_result_json)

        if cmd_output_list:
            cmd_output_result_json = json.dumps(sorted(cmd_output_list, key=lambda x: x["client"]))

            print(f"{TEXT_COLOR_CYAN}-------------------------------------------------------")
            print("Command output test")
            result = pd.read_json(cmd_output_result_json, orient="records")
            print(f"{result}{TEXT_COLOR_DEFAULT}")

            if download_json:
                dt = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
                file_name = f"cmd_output_test_result_{dt}.json"
                complete_name = os.path.join(save_path, file_name)

                with open(complete_name, "a+") as file:
                    file.write(cmd_output_result_json)

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
        default=7200,
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
        "--scp",
        action="store_true",
        help="Option to disable test",
    )
    parser.add_argument(
        "--scp-transfer-file-size",
        default=10,
        type=int,
        help="Sets scp transferred file size (in Mbytes, default: %(default)MB)",
    )
    parser.add_argument(
        "--cmd-output-count",
        default=0,
        type=int,
        help="Specifies the number of commands with output",
    )
    parser.add_argument(
        "--cmd-output-size",
        default=393216,
        type=int,
        help="Sets command output size",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Download results as json files",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        type=str,
        help="Sets output directory for results",
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
            scp=args.scp,
            scp_transfer_file_size=args.scp_transfer_file_size,
            cmd_output_count=args.cmd_output_count,
            cmd_output_size=args.cmd_output_size,
            download_json=args.json,
            output_dir=args.output_dir,
        ),
        log_file=args.log_file,
    )
