#!/usr/bin/env python3
"""Aggregate hierarchy and stripped-star checks per Gaia source/solution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.alternative_hypotheses import audit_alternative_hypotheses
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
    parser.add_argument(
        "checks",
        type=Path,
        help=(
            "long table with source_id, solution_id, hypothesis, check_name, outcome, "
            "and optional reference/notes"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/alternative_hypothesis_audit.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    checks = read_table(args.checks)
    keys = ["source_id", "solution_id"]
    required = {*keys, "hypothesis", "check_name", "outcome"}
    missing = sorted(required - set(checks.columns))
    if missing:
        raise KeyError(f"checks table is missing columns: {missing}")

    records: list[dict[str, object]] = []
    for key, group in checks.groupby(keys, dropna=False, sort=False):
        audit = audit_alternative_hypotheses(group.to_dict(orient="records"))
        records.append(
            {
                "source_id": key[0],
                "solution_id": key[1],
                **audit,
            }
        )
    output = pd.DataFrame.from_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)

    hierarchy_counts = {
        str(key): int(value)
        for key, value in output["hierarchy_audit_status"].value_counts().items()
    }
    stripped_counts = {
        str(key): int(value)
        for key, value in output["stripped_star_audit_status"].value_counts().items()
    }
    manifest = {
        "input": str(args.checks),
        "input_sha256": sha256_file(args.checks),
        "check_rows": len(checks),
        "source_solution_rows": len(output),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "hierarchy_status_counts": hierarchy_counts,
        "stripped_star_status_counts": stripped_counts,
        "interpretation_boundary": (
            "Statuses summarize supplied mandatory checks and do not prove a dark "
            "companion or exhaust all alternative hypotheses."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
