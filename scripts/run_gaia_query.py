#!/usr/bin/env python3
"""Execute a frozen Gaia ADQL query and emit a checksummed result manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.gaia import run_async_query, run_sync_query


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--query",
        type=Path,
        default=Path("queries/gaia_seed_pilot.adql"),
        help="Path to frozen ADQL query",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/gaia_seed_pilot.ecsv"),
        help="Output table path",
    )
    parser.add_argument(
        "--mode",
        choices=("async", "sync"),
        default="async",
        help="TAP execution mode; async is safer for joined or ordered Gaia queries",
    )
    parser.add_argument("--maxrec", type=int)
    parser.add_argument("--execution-duration-seconds", type=float, default=3600.0)
    parser.add_argument("--wait-timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--fetch-retries", type=int, default=3)
    parser.add_argument(
        "--keep-remote-job",
        action="store_true",
        help="do not delete the remote UWS job after fetching its result",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "sync":
        manifest = run_sync_query(
            args.query,
            args.output,
            overwrite=args.overwrite,
            maxrec=args.maxrec,
        )
    else:
        manifest = run_async_query(
            args.query,
            args.output,
            overwrite=args.overwrite,
            maxrec=args.maxrec,
            execution_duration_seconds=args.execution_duration_seconds,
            wait_timeout_seconds=args.wait_timeout_seconds,
            fetch_retries=args.fetch_retries,
            delete_job=not args.keep_remote_job,
        )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
