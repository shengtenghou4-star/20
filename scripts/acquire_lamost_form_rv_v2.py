#!/usr/bin/env python3
"""Acquire first-party LAMOST RV rows with current header normalization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.lamost_form_rv_v2 import acquire_form_rv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="CSV containing exact obsid values")
    parser.add_argument("--obsid-column", default="obsid")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--safe-summary", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--collection",
        choices=("minimal", "typical", "maximal"),
        default="minimal",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--maximum-response-mb", type=float, default=32.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--search-url",
        default="https://www.lamost.org/dr8/v1.0/search",
    )
    parser.add_argument(
        "--action-url",
        default="https://www.lamost.org/dr8/v1.0/q",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.maximum_response_mb <= 0:
        raise ValueError("--maximum-response-mb must be positive")
    summary = acquire_form_rv(
        obsid_input=args.input,
        obsid_column=args.obsid_column,
        output_path=args.output,
        private_manifest_path=args.private_manifest,
        safe_summary_path=args.safe_summary,
        batch_size=args.batch_size,
        collection=args.collection,
        timeout=args.timeout,
        maximum_response_bytes=int(args.maximum_response_mb * 1024**2),
        retries=args.retries,
        search_url=args.search_url,
        action_url=args.action_url,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
