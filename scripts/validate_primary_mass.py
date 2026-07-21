#!/usr/bin/env python3
"""Build one independent primary-mass consensus row per Gaia solution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.primary_validation import validate_primary_mass_estimates


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
        "estimates",
        type=Path,
        help=(
            "long table with source_id, solution_id, method_family, mass_solar, "
            "mass_error_solar, and optional provenance"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/independent_primary_mass.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    estimates = read_table(args.estimates)
    keys = ["source_id", "solution_id"]
    required = {*keys, "method_family", "mass_solar", "mass_error_solar"}
    missing = sorted(required - set(estimates.columns))
    if missing:
        raise KeyError(f"estimates table is missing columns: {missing}")

    records: list[dict[str, object]] = []
    for key, group in estimates.groupby(keys, dropna=False, sort=False):
        result = validate_primary_mass_estimates(group.to_dict(orient="records"))
        records.append(
            {
                "source_id": key[0],
                "solution_id": key[1],
                **result,
            }
        )
    output = pd.DataFrame.from_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)

    status_counts = {
        str(key): int(value)
        for key, value in output["independent_primary_status"].value_counts().items()
    }
    manifest = {
        "input": str(args.estimates),
        "input_sha256": sha256_file(args.estimates),
        "estimate_rows": len(estimates),
        "source_solution_rows": len(output),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "status_counts": status_counts,
        "interpretation_boundary": (
            "The consensus summarizes supplied method families. Shared systematics, "
            "model assumptions, and unresolved companion light remain mandatory audits."
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
