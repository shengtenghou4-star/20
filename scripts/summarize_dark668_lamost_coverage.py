#!/usr/bin/env python3
"""Summarize Dark-668 cadence and raw RV spread from LAMOST MEC overlap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.dark668_coverage import (
    candidate_safe_coverage_summary,
    summarize_period_coverage,
)
from hou_compact.gaia import sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("epochs", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_lamost_coverage.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_lamost_coverage_summary.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    epochs = pd.read_csv(args.epochs, dtype={"source_id": "string"})
    coverage = summarize_period_coverage(candidates, epochs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(args.output, index=False)

    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "candidate_input_sha256": sha256_file(args.candidates),
        "epoch_input_sha256": sha256_file(args.epochs),
        "summary": candidate_safe_coverage_summary(coverage),
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": "Never commit or upload the source-level coverage table.",
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
