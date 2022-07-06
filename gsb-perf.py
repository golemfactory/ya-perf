#!/usr/bin/env python3
from datetime import datetime
import pathlib
import sys
from typing import cast, Optional

from yapapi.storage import gftp

examples_dir = pathlib.Path(__file__).resolve().parent.parent
sys.path.append(str(examples_dir))

from utils import (
    build_parser,
    run_golem_example,
)


class GftpProviderExt(gftp.GftpProvider):
    def __init__(self, *, tmpdir: Optional[str] = None):
        super().__init__(tmpdir=tmpdir)

    async def download(self, url, output_file):
        process = await self._GftpProvider__get_process()

        async with self._lock:
            await process.download(url=url, output_file=output_file)


async def main(transfer_file_size):
    value = bytes(transfer_file_size * 1024 * 1024)

    async with GftpProviderExt() as transfers:
        link = await transfers.upload_bytes(value)
        print(f"Download link: {link.download_url}")

        before = datetime.now().timestamp()
        await transfers.download(link.download_url, "output.bin")
        after = datetime.now().timestamp()

        dt = after - before
        transfer_speed = (transfer_file_size / dt).__round__(3)
        print(f"Transfer speed: {transfer_speed} MB/s")


if __name__ == "__main__":
    parser = build_parser("GSB transfer measuring tool")

    parser.add_argument(
        "--transfer-file-size",
        default=20,
        type=int,
        help="Sets transferred file size (in Mbytes, default: %(default)MB)",
    )

    now = datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    parser.set_defaults(log_file=f"ya-gsb-perf-{now}.log")
    args = parser.parse_args()

    run_golem_example(
        main(
            transfer_file_size=args.transfer_file_size,
        ),
        log_file=args.log_file,
    )
