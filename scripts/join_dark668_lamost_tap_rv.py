#!/usr/bin/env python3
"""Join exact LAMOST TAP RV products to Dark-668 MEC epochs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.dark668_lamost import (
    candidate_safe_join_summary,
    join_and_standardize_tap_rv,
)
from hou_compact.gaia import sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("epochs", type=Path)
    parser.add_argument("tap_rows", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_lamost_scorable_epochs.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_lamost_join_summary.json"),
    )
    parser.add_argument("--maximum-rv-difference-kms", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    epochs = pd.read_csv(
        args.epochs,
        dtype={"source_id": "string", "dr2_source_id": "string", "obsid": "string"},
    )
    tap_rows = pd.read_csv(args.tap_rows, dtype={"obsid": "string"})
    joined = join_and_standardize_tap_rv(
        epochs,
        tap_rows,
        maximum_rv_difference_kms=args.maximum_rv_difference_kms,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joined.to_csv(args.output, index=False)
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "epoch_input_sha256": sha256_file(args.epochs),
        "tap_input_sha256": sha256_file(args.tap_rows),
        "maximum_rv_difference_kms": args.maximum_rv_difference_kms,
        "summary": candidate_safe_join_summary(joined),
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": "Never commit or upload the source-level joined epochs.",
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
