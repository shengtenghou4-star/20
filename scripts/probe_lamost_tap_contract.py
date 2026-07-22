#!/usr/bin/env python3
"""Verify the LAMOST DR8 multiple-epoch schema through the official TAP service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.lamost_openapi import DEFAULT_OPENAPI_ROOT, discover_openapi_contract
from hou_compact.lamost_tap import discover_lamost_tap_contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default=DEFAULT_OPENAPI_ROOT)
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v1.0")
    parser.add_argument("--tap-url", default=None)
    parser.add_argument("--maximum-tables", type=int, default=10_000)
    parser.add_argument("--maximum-columns", type=int, default=100_000)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tap_url = args.tap_url
    openapi = None
    if tap_url is None:
        openapi = discover_openapi_contract(
            openapi_root=args.openapi_root,
            dr_version=args.dr_version,
            sub_version=args.sub_version,
        )
        urls = list(openapi["tap_urls"])
        if len(urls) != 1:
            raise RuntimeError(f"expected exactly one TAP URL, received {urls}")
        tap_url = str(urls[0])
    result = discover_lamost_tap_contract(
        tap_url,
        maximum_tables=args.maximum_tables,
        maximum_columns=args.maximum_columns,
    )
    payload = {
        "openapi": openapi,
        "tap_schema": result,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
