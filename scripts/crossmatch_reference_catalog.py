#!/usr/bin/env python3
"""Crossmatch private HOU-COMPACT follow-up rows to one reference catalogue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.catalog_crossmatch import (
    CatalogCrossmatchConfig,
    crossmatch_reference_catalog,
)
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
    parser.add_argument("gaia", type=Path, help="Gaia candidate or follow-up table")
    parser.add_argument("catalog", type=Path, help="reference catalogue table")
    parser.add_argument("--catalog-name", required=True)
    parser.add_argument("--catalog-id-column", default="catalog_id")
    parser.add_argument("--catalog-ra-column", default="ra")
    parser.add_argument("--catalog-dec-column", default="dec")
    parser.add_argument("--catalog-epoch-jyear", type=float, default=2000.0)
    parser.add_argument("--maximum-separation-arcsec", type=float, default=2.0)
    parser.add_argument("--minimum-ambiguity-margin-arcsec", type=float, default=0.2)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/reference_catalog_crossmatch.csv"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gaia = read_table(args.gaia)
    catalog = read_table(args.catalog).rename(
        columns={
            args.catalog_id_column: "catalog_id",
            args.catalog_ra_column: "ra",
            args.catalog_dec_column: "dec",
        }
    )
    config = CatalogCrossmatchConfig(
        catalog_epoch_jyear=args.catalog_epoch_jyear,
        maximum_separation_arcsec=args.maximum_separation_arcsec,
        minimum_ambiguity_margin_arcsec=args.minimum_ambiguity_margin_arcsec,
    )
    result = crossmatch_reference_catalog(
        gaia,
        catalog,
        config=config,
        catalog_name=args.catalog_name,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value)
        for key, value in result["match_status"].value_counts().items()
    }
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "catalog_input": str(args.catalog),
        "catalog_input_sha256": sha256_file(args.catalog),
        "catalog_name": args.catalog_name,
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "gaia_rows": len(gaia),
        "catalog_rows": len(catalog),
        "output_rows": len(result),
        "status_counts": status_counts,
        "manual_review_rows": int(result["match_requires_manual_review"].sum()),
        "configuration": {
            "catalog_epoch_jyear": config.catalog_epoch_jyear,
            "maximum_separation_arcsec": config.maximum_separation_arcsec,
            "minimum_ambiguity_margin_arcsec": (
                config.minimum_ambiguity_margin_arcsec
            ),
        },
        "interpretation_boundary": (
            "Positional associations are navigation evidence only. Identity, prior discovery, "
            "and astrophysical classification require manual validation."
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
