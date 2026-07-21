#!/usr/bin/env python3
"""Reduce retrieved catalogue/literature matches into one novelty audit per source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.novelty import audit_novelty_records


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", type=Path, help="unique source/solution key table")
    parser.add_argument("matches", type=Path, help="retrieved crossmatch/literature records")
    parser.add_argument(
        "--searched-service",
        action="append",
        required=True,
        help="service that was searched completely; repeat for each service",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/novelty_audit.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sources = read_table(args.sources)
    matches = read_table(args.matches)
    keys = ["source_id", "solution_id"]
    missing_sources = [key for key in keys if key not in sources]
    missing_matches = [key for key in keys if key not in matches]
    if missing_sources:
        raise KeyError(f"sources table is missing keys: {missing_sources}")
    if missing_matches:
        raise KeyError(f"matches table is missing keys: {missing_matches}")
    if sources.duplicated(keys).any():
        raise ValueError("sources table contains duplicate source/solution rows")

    grouped = {
        tuple(key): group
        for key, group in matches.groupby(keys, dropna=False, sort=False)
    }
    records: list[dict[str, object]] = []
    for _, source in sources.iterrows():
        key = (source["source_id"], source["solution_id"])
        group = grouped.get(key, matches.iloc[0:0])
        audit = audit_novelty_records(
            group.to_dict(orient="records"),
            searched_services=args.searched_service,
        )
        records.append(
            {
                "source_id": source["source_id"],
                "solution_id": source["solution_id"],
                **audit,
            }
        )

    output = pd.DataFrame.from_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value)
        for key, value in output["novelty_audit_status"].value_counts().items()
    }
    manifest = {
        "sources_input": str(args.sources),
        "sources_input_sha256": sha256_file(args.sources),
        "matches_input": str(args.matches),
        "matches_input_sha256": sha256_file(args.matches),
        "source_rows": len(sources),
        "match_rows": len(matches),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "output_rows": len(output),
        "searched_services": sorted(set(args.searched_service)),
        "status_counts": status_counts,
        "interpretation_boundary": (
            "A complete no-prior-claim status records search precedence only. It does "
            "not prove astrophysical novelty or validate a compact companion."
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
