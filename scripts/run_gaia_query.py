#!/usr/bin/env python3
"""Execute a frozen Gaia ADQL query and emit a checksummed result manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.gaia import run_sync_query


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
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = run_sync_query(args.query, args.output, overwrite=args.overwrite)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
