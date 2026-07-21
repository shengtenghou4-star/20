#!/usr/bin/env python3
"""Apply the final HOU-COMPACT claim-readiness policy to a merged evidence table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.claim_readiness import assess_claim_readiness
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
    parser.add_argument("evidence", type=Path, help="merged source-level evidence table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/claim_readiness.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence = read_table(args.evidence)
    keys = ["source_id", "solution_id"]
    missing = [key for key in keys if key not in evidence.columns]
    if missing:
        raise KeyError(f"evidence table is missing keys: {missing}")
    if evidence.duplicated(keys).any():
        raise ValueError("evidence table contains duplicate source/solution rows")

    records: list[dict[str, object]] = []
    for _, row in evidence.iterrows():
        result = assess_claim_readiness(row)
        records.append(
            {
                "source_id": row["source_id"],
                "solution_id": row["solution_id"],
                **result,
            }
        )
    output = pd.DataFrame.from_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)

    status_counts = {
        str(key): int(value)
        for key, value in output["claim_readiness_status"].value_counts().items()
    }
    manifest = {
        "input": str(args.evidence),
        "input_sha256": sha256_file(args.evidence),
        "input_rows": len(evidence),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "output_rows": len(output),
        "status_counts": status_counts,
        "claim_authorized_count": int(output["claim_authorized"].sum()),
        "interpretation_boundary": (
            "The strongest status is claim_audit_ready_not_classified. This command "
            "never authorizes or emits a compact-object classification."
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
