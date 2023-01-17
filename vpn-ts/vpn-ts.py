#!/usr/bin/env python3
import asyncio
from datetime import datetime, timedelta
import pathlib
import random
import string
import sys

from yapapi import Golem
from yapapi.contrib.service.socket_proxy import SocketProxy, SocketProxyService
from yapapi.payload import vm

# the timeout after we commission our service instances
# before we abort this script
STARTING_TIMEOUT = timedelta(minutes=4)


examples_dir = pathlib.Path(__file__).resolve().parent.parent
sys.path.append(str(examples_dir))

from utils import (
    TEXT_COLOR_CYAN,
    TEXT_COLOR_DEFAULT,
    TEXT_COLOR_RED,
    TEXT_COLOR_YELLOW,
    build_parser,
    print_env_info,
    run_golem_example,
)


class SshService(SocketProxyService):
    remote_port = 7132

    def __init__(self, proxy: SocketProxy):
        super().__init__()
        self.proxy = proxy

    @staticmethod
    async def get_payload():
        return await vm.repo(
            image_hash="6e5242d501a7893f594ccfce45251ef61175335e812c9ce1ce64a12b",
            min_mem_gib=0.5,
            min_storage_gib=2.0,
            # we're adding an additional constraint to only select those nodes that
            # are offering VPN-capable VM runtimes so that we can connect them to the VPN
            capabilities=[vm.VM_CAPS_VPN],
        )

    async def start(self):
        # perform the initialization of the Service
        # (which includes sending the network details within the `deploy` command)
        async for script in super().start():
            yield script

        script = self._ctx.new_script(timeout=timedelta(seconds=10))
        script.run("/usr/bin/run.sh", "192.168.0.2", "100", "1000")
        yield script

        server = await self.proxy.run_server(self, self.remote_port)


async def main(subnet_tag, payment_driver=None, payment_network=None, num_instances=2):
    # By passing `event_consumer=log_summary()` we enable summary logging.
    # See the documentation of the `yapapi.log` module on how to set
    # the level of detail and format of the logged information.
    async with Golem(
        budget=1.0,
        subnet_tag=subnet_tag,
        payment_driver=payment_driver,
        payment_network=payment_network,
    ) as golem:
        print_env_info(golem)

        network = await golem.create_network("192.168.0.1/24")
        proxy = SocketProxy(ports=range(2223, 2223 + num_instances))

        async with network:
            cluster = await golem.run_service(
                SshService,
                network=network,
                num_instances=num_instances,
                instance_params=[{"proxy": proxy} for _ in range(num_instances)],
            )
            instances = cluster.instances

            while True:
                print(instances)
                try:
                    await asyncio.sleep(5)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    break

            await proxy.stop()
            cluster.stop()

            cnt = 0
            while cnt < 3 and any(s.is_available for s in instances):
                print(instances)
                await asyncio.sleep(5)
                cnt += 1


if __name__ == "__main__":
    parser = build_parser("Golem VPN TS example")
    parser.add_argument(
        "--num-instances",
        type=int,
        default=1,
        help="Number of instances to spawn",
    )
    now = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    parser.set_defaults(log_file=f"vpn-ts-yapapi-{now}.log")
    args = parser.parse_args()

    run_golem_example(
        main(
            subnet_tag=args.subnet_tag,
            payment_driver=args.payment_driver,
            payment_network=args.payment_network,
            num_instances=args.num_instances,
        ),
        log_file=args.log_file,
    )
