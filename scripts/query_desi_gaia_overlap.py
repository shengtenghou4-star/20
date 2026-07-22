#!/usr/bin/env python3
"""Query the official NOIRLab Gaia DR3 ↔ DESI DR1 zpix crossmatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.datalab import DataLabQueryConfig
from hou_compact.datalab_query_manager import query_desi_gaia_overlap_v2
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
    parser.add_argument("gaia", type=Path, help="Gaia seed table containing source_id")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_gaia_exact_overlap.csv"),
    )
    parser.add_argument("--batch-size", type=int, default=150)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--service-url",
        default="https://datalab.noirlab.edu/query",
        help="NOIRLab Data Lab Query Manager service root",
    )
    parser.add_argument(
        "--program",
        action="append",
        default=[],
        help="DESI program to retain; repeat as needed (default: bright,dark)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gaia = read_table(args.gaia)
    if "source_id" not in gaia.columns:
        raise KeyError("Gaia input has no source_id column")
    source_ids = pd.to_numeric(gaia["source_id"], errors="raise").astype("int64")
    if source_ids.duplicated().any():
        raise ValueError("Gaia input contains duplicate source_id values")
    programs = tuple(args.program) if args.program else ("bright", "dark")
    config = DataLabQueryConfig(
        service_url=args.service_url,
        timeout_seconds=args.timeout,
        retries=args.retries,
        batch_size=args.batch_size,
    )
    overlap, receipts = query_desi_gaia_overlap_v2(
        source_ids,
        programs=programs,
        config=config,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    overlap.to_csv(args.output, index=False)
    files = (
        overlap[["survey", "program", "healpix"]]
        .drop_duplicates()
        .sort_values(["survey", "program", "healpix"], kind="stable")
        .reset_index(drop=True)
    )
    files_path = args.output.with_suffix(".files.csv")
    files.to_csv(files_path, index=False)

    matched_sources = int(overlap["source_id"].nunique()) if not overlap.empty else 0
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "files_output": str(files_path),
        "files_output_sha256": sha256_file(files_path),
        "input_source_count": int(source_ids.nunique()),
        "matched_source_count": matched_sources,
        "unmatched_source_count": int(source_ids.nunique()) - matched_sources,
        "overlap_rows": len(overlap),
        "exact_file_count": len(files),
        "program_counts": {
            str(key): int(value)
            for key, value in overlap["program"].value_counts().items()
        },
        "maximum_match_distance_arcsec": (
            float(overlap["match_distance_arcsec"].max()) if not overlap.empty else None
        ),
        "query_service": config.service_url,
        "query_transport": "official_query_manager_nested_query_endpoint",
        "query_profile": config.profile,
        "crossmatch_table": "gaia_dr3.x1p5__gaia_source__desi_dr1__zpix",
        "desi_table": "desi_dr1.zpix",
        "batch_size": config.batch_size,
        "batch_receipts": [receipt.to_record() for receipt in receipts],
        "claim_boundary": (
            "This file is an exact public-catalogue crossmatch, not orbit support or a "
            "compact-object classification. Source-level output is candidate-sensitive "
            "and belongs in the encrypted evidence vault."
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
