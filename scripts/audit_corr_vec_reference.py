#!/usr/bin/env python3
"""Compare live Gaia corr_vec rows with the independent DPAC nsstools decoder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.reference_covariance import compare_with_nsstools


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path, help="live Gaia SB1/SB1C table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/corr_vec_reference_audit.csv"),
    )
    parser.add_argument("--max-rows", type=int, default=100)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_rows < 1:
        raise ValueError("max_rows must be positive")
    if args.absolute_tolerance < 0:
        raise ValueError("absolute_tolerance must be non-negative")

    gaia = read_table(args.gaia)
    required = {"source_id", "solution_id", "nss_solution_type", "bit_index", "corr_vec"}
    missing = sorted(required - set(gaia.columns))
    if missing:
        raise KeyError(f"Gaia input is missing columns: {missing}")

    records: list[dict[str, object]] = []
    for _, row in gaia.head(args.max_rows).iterrows():
        record: dict[str, object] = {
            "source_id": row["source_id"],
            "solution_id": row["solution_id"],
            "nss_solution_type": row["nss_solution_type"],
            "bit_index": row["bit_index"],
            "status": "error",
            "error": "",
        }
        try:
            comparison = compare_with_nsstools(row.to_dict())
            difference = comparison.maximum_absolute_difference
            record.update(
                {
                    "status": "pass" if difference <= args.absolute_tolerance else "mismatch",
                    "maximum_absolute_difference": difference,
                    "parameter_names": ";".join(comparison.parameter_names),
                    "decoding_mode": comparison.decoding_mode,
                    "raw_vector_length": comparison.raw_vector_length,
                    "coefficient_count": comparison.coefficient_count,
                }
            )
        except (TypeError, ValueError, RuntimeError, KeyError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)

    result = pd.DataFrame.from_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value) for key, value in result["status"].value_counts().items()
    }
    passed = result.loc[result["status"].eq("pass")]
    maximum_difference = (
        float(passed["maximum_absolute_difference"].max()) if not passed.empty else None
    )
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "rows_attempted": len(result),
        "status_counts": status_counts,
        "absolute_tolerance": args.absolute_tolerance,
        "maximum_passing_absolute_difference": maximum_difference,
        "reference_package": "nsstools==0.1.12",
        "interpretation_boundary": (
            "This audit validates covariance reconstruction parity only. It does not "
            "validate an orbit, companion mass, or compact-object interpretation."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))

    if status_counts.get("mismatch", 0) or status_counts.get("error", 0):
        raise RuntimeError("one or more Gaia covariance reference comparisons failed")


if __name__ == "__main__":
    main()
