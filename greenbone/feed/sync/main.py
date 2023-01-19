# Copyright (C) 2022 Greenbone Networks GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Iterable, NoReturn

from greenbone.feed.sync.errors import GreenboneFeedSyncError, RsyncError
from greenbone.feed.sync.helper import flock_wait
from greenbone.feed.sync.parser import CliParser
from greenbone.feed.sync.rsync import Rsync

__all__ = ("main",)


def is_root() -> bool:
    """
    Checks if the current user is root
    """
    return os.geteuid() == 0


@dataclass
class Sync:
    """
    Class to store sync information
    """

    name: str
    types: list[str]
    url: str
    destination: str


@dataclass
class SyncList:
    """
    Class to store a list of sync information
    """

    lock_file: str
    syncs: list[Sync]


def filter_syncs(lock_file, feed_type: str, *syncs: Iterable[Sync]) -> SyncList:
    """
    Create a list of syncs which only match to the feed type
    """
    return SyncList(
        lock_file=lock_file,
        syncs=[sync for sync in syncs if feed_type in sync.types],
    )


async def feed_sync() -> int:
    """
    Sync the feeds
    """
    if is_root():
        raise GreenboneFeedSyncError(
            "The sync script should not be run as root. Running the script as "
            "root may cause several hard to find permissions issues."
        )

    parser = CliParser()
    args = parser.parse_arguments()

    rsync = Rsync(
        private_subdir=args.private_directory,
        verbose=args.verbose >= 3,
        compression_level=args.compression_level,
    )

    openvas_syncs = filter_syncs(
        args.openvas_lock_file,
        args.type,
        Sync(
            name="Notus files",
            types=("notus", "nvt", "all"),
            url=args.notus_url,
            destination=args.notus_destination,
        ),
        Sync(
            name="NASL files",
            types=("nasl", "nvt", "all"),
            url=args.nasl_url,
            destination=args.nasl_destination,
        ),
    )
    gvmd_syncs = filter_syncs(
        args.gvmd_lock_file,
        args.type,
        Sync(
            name="SCAP data",
            types=("scap", "all"),
            url=args.scap_data_url,
            destination=args.scap_data_destination,
        ),
        Sync(
            name="CERT-Bund data",
            types=("cert", "all"),
            url=args.cert_data_url,
            destination=args.cert_data_destination,
        ),
        Sync(
            name="report formats",
            types=("report-format", "gvmd-data", "all"),
            url=args.report_formats_url,
            destination=args.report_formats_destination,
        ),
        Sync(
            name="scan configs",
            types=("scan-config", "gvmd-data", "all"),
            url=args.scan_configs_url,
            destination=args.scan_configs_destination,
        ),
        Sync(
            name="port lists",
            types=("port-list", "gvmd-data", "all"),
            url=args.port_lists_url,
            destination=args.port_lists_destination,
        ),
    )

    has_error = False
    wait_interval = None if args.no_wait else args.wait_interval

    for sync_list in (openvas_syncs, gvmd_syncs):
        if not sync_list.syncs:
            continue

        async with flock_wait(
            sync_list.lock_file,
            verbose=args.verbose >= 2,
            wait_interval=wait_interval,
        ):
            for sync in sync_list.syncs:
                try:
                    if args.verbose >= 1:
                        print(
                            f"Downloading {sync.name} from {sync.url} to "
                            f"{sync.destination}"
                        )
                    await rsync.sync(url=sync.url, destination=sync.destination)
                except RsyncError as e:
                    print(e.stderr, file=sys.stderr)
                    if args.fail_fast:
                        return 1
                    has_error = True

    return 1 if has_error else 0


def main() -> NoReturn:
    """
    Main CLI function
    """
    try:
        sys.exit(asyncio.run(feed_sync()))
    except GreenboneFeedSyncError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
