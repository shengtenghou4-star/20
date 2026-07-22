#!/usr/bin/env python3
"""Probe official LAMOST DR8 catalogue files without downloading them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.lamost_catalog_files import probe_catalogue_file


DEFAULT_BASE = "https://www.lamost.org/dr8/v1.0/catdl?name="
DEFAULT_FILES = (
    "dr8_v1.0_LRS_mec.csv.gz",
    "dr8_v1.0_catalogue_LRS.csv.gz",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--file", action="append", dest="files")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--prefix-bytes", type=int, default=4096)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    filenames = tuple(args.files or DEFAULT_FILES)
    probes = []
    for filename in filenames:
        url = f"{args.base_url}{filename}"
        probe = probe_catalogue_file(
            url,
            timeout=args.timeout,
            retries=args.retries,
            prefix_bytes=args.prefix_bytes,
        )
        probes.append(probe.to_record())
    payload = {
        "status": "pass",
        "file_count": len(probes),
        "files": probes,
        "claim_boundary": (
            "Each request reads only a bounded compressed prefix. No catalogue row "
            "is decompressed, parsed, or classified."
        ),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
