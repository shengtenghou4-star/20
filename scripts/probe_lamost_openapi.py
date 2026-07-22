#!/usr/bin/env python3
"""Discover the machine-readable LAMOST DR8 v1.0 access contract."""

from __future__ import annotations

import argparse
import json

from hou_compact.lamost_openapi import (
    DEFAULT_OPENAPI_ROOT,
    discover_openapi_contract,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default=DEFAULT_OPENAPI_ROOT)
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v1.0")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--maximum-response-bytes",
        type=int,
        default=16 * 1024 * 1024,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = discover_openapi_contract(
        openapi_root=args.openapi_root,
        dr_version=args.dr_version,
        sub_version=args.sub_version,
        timeout=args.timeout,
        retries=args.retries,
        maximum_response_bytes=args.maximum_response_bytes,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
