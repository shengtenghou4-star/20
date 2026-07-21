#!/usr/bin/env python3
"""Merge final source-level evidence tables and apply claim-readiness policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.evidence_merge import merge_claim_evidence
from hou_compact.gaia import sha256_file


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_named_path(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("evidence must use NAME=PATH syntax")
    name, raw_path = value.split("=", 1)
    name = name.strip()
    raw_path = raw_path.strip()
    if not name or not raw_path:
        raise argparse.ArgumentTypeError("evidence NAME and PATH must be non-empty")
    return name, Path(raw_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path, help="base triage/evidence table")
    parser.add_argument(
        "--evidence",
        action="append",
        type=parse_named_path,
        required=True,
        metavar="NAME=PATH",
        help="named one-row-per-source evidence table; repeat for each table",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/merged_claim_evidence.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence_paths: dict[str, Path] = {}
    for name, path in args.evidence:
        if name in evidence_paths:
            raise ValueError(f"duplicate evidence name: {name}")
        evidence_paths[name] = path

    base = read_table(args.base)
    evidence_tables = {
        name: read_table(path) for name, path in evidence_paths.items()
    }
    result = merge_claim_evidence(base, evidence_tables)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.frame.to_csv(args.output, index=False)

    status_counts = {
        str(key): int(value)
        for key, value in result.frame["claim_readiness_status"].value_counts().items()
    }
    manifest = {
        "base_input": str(args.base),
        "base_input_sha256": sha256_file(args.base),
        "base_rows": len(base),
        "evidence_inputs": {
            name: {
                "path": str(path),
                "sha256": sha256_file(path),
                "rows": len(evidence_tables[name]),
            }
            for name, path in evidence_paths.items()
        },
        "coverage": result.coverage,
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "output_rows": len(result.frame),
        "claim_readiness_status_counts": status_counts,
        "claim_authorized_count": int(result.frame["claim_authorized"].sum()),
        "interpretation_boundary": (
            "Merged evidence may reach claim_audit_ready_not_classified, but this command "
            "never authorizes an astrophysical classification."
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
