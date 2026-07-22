#!/usr/bin/env python3
"""Run the frozen candidate-safe HOU-COMPACT triage sensitivity grid."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.sensitivity import (
    SensitivityGrid,
    candidate_safe_sensitivity_summary,
    run_triage_sensitivity,
)


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "triage",
        type=Path,
        help="row-complete followup_triage product containing merged evidence columns",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/triage_sensitivity.csv"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="candidate-safe JSON summary; defaults beside --output",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    triage = read_table(args.triage)
    grid = SensitivityGrid()
    results = run_triage_sensitivity(triage, grid=grid)
    summary = candidate_safe_sensitivity_summary(results)
    summary_output = args.summary_output or args.output.with_suffix(
        args.output.suffix + ".summary.json"
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.output, index=False)
    payload = {
        **summary,
        "triage_input": str(args.triage),
        "triage_input_sha256": sha256_file(args.triage),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "grid": {
            "min_clean_desi_epochs": list(grid.min_clean_desi_epochs),
            "min_phase_coverage": list(grid.min_phase_coverage),
            "min_delta_chi2": list(grid.min_delta_chi2),
            "max_primary_fractional_width": list(
                grid.max_primary_fractional_width
            ),
        },
    }
    summary_output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
