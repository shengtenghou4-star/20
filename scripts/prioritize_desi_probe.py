#!/usr/bin/env python3
"""Rank existing DESI files for a byte-bounded private acquisition pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.prioritization import prioritize_desi_probe


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path, help="Gaia seed table")
    parser.add_argument("probe", type=Path, help="DESI probe table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_probe_prioritized.csv"),
    )
    parser.add_argument("--include-nonexistent", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gaia = read_table(args.gaia)
    probe = read_table(args.probe)
    ranked = prioritize_desi_probe(
        gaia,
        probe,
        existing_only=not args.include_nonexistent,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(args.output, index=False)
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "probe_input": str(args.probe),
        "probe_input_sha256": sha256_file(args.probe),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "input_probe_rows": len(probe),
        "ranked_rows": len(ranked),
        "unique_ranked_healpix": int(ranked["healpix"].nunique()) if not ranked.empty else 0,
        "maximum_seed_source_count": (
            int(ranked["seed_source_count"].max()) if not ranked.empty else 0
        ),
        "existing_only": not args.include_nonexistent,
        "ranking_rule": (
            "descending Gaia seed count per NSIDE=64 nested HEALPix; main bright, "
            "main dark, then backup for ties"
        ),
        "interpretation_boundary": (
            "File priority optimizes bounded data acquisition and does not use or imply "
            "candidate mass, orbit quality, or compact-object status."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
