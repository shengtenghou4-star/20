#!/usr/bin/env python3
"""Build candidate-safe attrition tables from a HOU-COMPACT triage product."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.attrition import candidate_safe_attrition_summary, sequential_attrition
from hou_compact.gaia import sha256_file


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("triage", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/followup_attrition_summary.json"),
    )
    parser.add_argument(
        "--flow-output",
        type=Path,
        help="sequential entered/held/advanced CSV; defaults beside --output",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    triage = read_table(args.triage)
    summary = candidate_safe_attrition_summary(triage)
    flow = sequential_attrition(triage)
    flow_output = args.flow_output or args.output.with_name(
        args.output.stem + ".flow.csv"
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    flow_output.parent.mkdir(parents=True, exist_ok=True)
    flow.to_csv(flow_output, index=False)

    payload = {
        **summary,
        "triage_input": str(args.triage),
        "triage_input_sha256": sha256_file(args.triage),
        "flow_output": str(flow_output),
        "flow_output_sha256": sha256_file(flow_output),
    }
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
