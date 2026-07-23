#!/usr/bin/env python3
"""Acquire all LAMOST spectra for accepted exact Gaia DR2 bridge IDs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.lamost_gaia_form_rv_v3 import (
    acquire_gaia_form_rv_sessioned_zero_aware,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bridge", type=Path)
    parser.add_argument("--rows-output", type=Path, required=True)
    parser.add_argument("--overlap-output", type=Path, required=True)
    parser.add_argument("--private-manifest", type=Path, required=True)
    parser.add_argument("--safe-summary", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--batches-per-session",
        type=int,
        default=5,
        help="maximum successful form POST batches per fresh cookie session",
    )
    parser.add_argument(
        "--collection",
        choices=("minimal", "typical", "maximal"),
        default="minimal",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--maximum-response-mb", type=float, default=32.0)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.maximum_response_mb <= 0:
        raise ValueError("--maximum-response-mb must be positive")
    summary = acquire_gaia_form_rv_sessioned_zero_aware(
        bridge_input=args.bridge,
        rows_output=args.rows_output,
        overlap_output=args.overlap_output,
        private_manifest_path=args.private_manifest,
        safe_summary_path=args.safe_summary,
        batch_size=args.batch_size,
        batches_per_session=args.batches_per_session,
        collection=args.collection,
        timeout=args.timeout,
        maximum_response_bytes=int(args.maximum_response_mb * 1024**2),
        retries=args.retries,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
