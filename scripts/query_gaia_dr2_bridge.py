#!/usr/bin/env python3
"""Retrieve and audit Gaia DR3-to-DR2 identifiers for DESI REF_ID recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.gaia_dr2_bridge import GaiaDr2BridgeConfig, audit_gaia_dr2_bridge
from hou_compact.gaia_dr2_bridge_v2 import query_gaia_dr2_neighbourhood_v2


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path, help="Gaia DR3 seed table containing source_id")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/gaia_dr2_bridge.csv"),
        help="audited one-row-per-DR3-source bridge",
    )
    parser.add_argument(
        "--neighbourhood-output",
        type=Path,
        help="raw all-neighbour table; defaults beside --output",
    )
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--maxrec-per-batch", type=int, default=5000)
    parser.add_argument("--maximum-nearest-distance-mas", type=float, default=1000.0)
    parser.add_argument("--minimum-distance-margin-mas", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gaia = read_table(args.gaia)
    if "source_id" not in gaia.columns:
        raise KeyError("Gaia input has no source_id column")
    source_ids = pd.to_numeric(gaia["source_id"], errors="raise").astype("int64")
    if source_ids.duplicated().any():
        raise ValueError("Gaia input contains duplicate source_id rows")

    config = GaiaDr2BridgeConfig(
        batch_size=args.batch_size,
        maxrec_per_batch=args.maxrec_per_batch,
    )
    neighbours, receipts = query_gaia_dr2_neighbourhood_v2(
        source_ids,
        config=config,
    )
    audited = audit_gaia_dr2_bridge(
        neighbours,
        maximum_nearest_distance_mas=args.maximum_nearest_distance_mas,
        minimum_distance_margin_mas=args.minimum_distance_margin_mas,
    )

    neighbourhood_output = args.neighbourhood_output or args.output.with_name(
        args.output.stem + ".neighbourhood.csv"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    neighbourhood_output.parent.mkdir(parents=True, exist_ok=True)
    neighbours.to_csv(neighbourhood_output, index=False)
    audited.to_csv(args.output, index=False)

    status_counts = {
        str(key): int(value)
        for key, value in audited["dr2_bridge_status"].value_counts().items()
    }
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "input_source_count": int(source_ids.nunique()),
        "neighbourhood_output": str(neighbourhood_output),
        "neighbourhood_output_sha256": sha256_file(neighbourhood_output),
        "neighbourhood_rows": len(neighbours),
        "neighbourhood_source_count": (
            int(neighbours["dr3_source_id"].nunique()) if not neighbours.empty else 0
        ),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "audited_rows": len(audited),
        "status_counts": status_counts,
        "accepted_source_count": int(
            audited["dr2_bridge_status"]
            .eq("accepted_unique_or_separated_nearest")
            .sum()
        ),
        "settings": {
            "batch_size": config.batch_size,
            "maxrec_per_batch": config.maxrec_per_batch,
            "maximum_nearest_distance_mas": args.maximum_nearest_distance_mas,
            "minimum_distance_margin_mas": args.minimum_distance_margin_mas,
            "server_ordering": "plain_columns_only",
            "client_tie_break": "absolute_magnitude_difference",
        },
        "batch_receipts": [receipt.to_record() for receipt in receipts],
        "interpretation_boundary": (
            "The bridge connects Gaia release identifiers. Acceptance does not prove that "
            "a DESI spectrum belongs to the DR3 source until exact FIBERMAP REF_CAT='G2' "
            "and REF_ID equality is demonstrated."
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
