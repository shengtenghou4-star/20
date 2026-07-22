#!/usr/bin/env python3
"""Discover first-party LAMOST DR8 catalogue download references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.lamost_catalogue import discover_catalogue_links


DEFAULT_PAGE_URL = "https://www.lamost.org/dr8/v1.0/catalogue"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page-url", default=DEFAULT_PAGE_URL)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--maximum-response-bytes",
        type=int,
        default=8 * 1024 * 1024,
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = discover_catalogue_links(
        args.page_url,
        timeout=args.timeout,
        retries=args.retries,
        maximum_response_bytes=args.maximum_response_bytes,
    )
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
