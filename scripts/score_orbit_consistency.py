#!/usr/bin/env python3
"""Compare fixed Gaia SB1 orbit shapes with independent DESI RV visits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.validation import score_orbit_consistency


def read_table(path: Path) -> pd.DataFrame:
    """Read CSV, Parquet, ECSV, or FITS into a pandas dataframe."""
    suffixes = [suffix.lower() for suffix in path.suffixes]
    if suffixes and suffixes[-1] == ".csv":
        return pd.read_csv(path)
    if suffixes and suffixes[-1] in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path, help="Gaia SB1 seed table")
    parser.add_argument("epochs", type=Path, help="Extracted DESI exposure table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/orbit_consistency.csv"),
    )
    parser.add_argument(
        "--min-clean-epochs",
        type=int,
        default=2,
        help="minimum independent visits; legacy option name retained for compatibility",
    )
    parser.add_argument("--min-arm-sn", type=float, default=2.0)
    parser.add_argument("--max-vrad-err", type=float, default=20.0)
    parser.add_argument("--jitter-kms", type=float, default=0.0)
    parser.add_argument("--maximum-visit-gap-hours", type=float, default=2.0)
    parser.add_argument("--visit-error-floor-kms", type=float, default=0.0)
    parser.add_argument(
        "--disable-visit-aggregation",
        action="store_true",
        help="treat each clean exposure as independent for sensitivity analysis only",
    )
    parser.add_argument(
        "--include-backup",
        action="store_true",
        help="include backup-program rows only after a validated correction is applied",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gaia = read_table(args.gaia)
    epochs = read_table(args.epochs)
    excluded = () if args.include_backup else ("backup",)
    result = score_orbit_consistency(
        gaia,
        epochs,
        min_clean_epochs=args.min_clean_epochs,
        min_arm_sn=args.min_arm_sn,
        max_vrad_err=args.max_vrad_err,
        jitter_kms=args.jitter_kms,
        exclude_programs=excluded,
        aggregate_visits=not args.disable_visit_aggregation,
        maximum_visit_gap_hours=args.maximum_visit_gap_hours,
        visit_error_floor_kms=args.visit_error_floor_kms,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value) for key, value in result["status"].value_counts().items()
    }
    visit_counts = {
        str(key): int(value)
        for key, value in result["n_independent_visits"].value_counts().sort_index().items()
    }
    exposure_counts = {
        str(key): int(value)
        for key, value in result["n_clean_exposures"].value_counts().sort_index().items()
    }
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "epoch_input": str(args.epochs),
        "epoch_input_sha256": sha256_file(args.epochs),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "gaia_solution_rows": len(gaia),
        "epoch_rows": len(epochs),
        "output_rows": len(result),
        "status_counts": status_counts,
        "independent_visit_count_distribution": visit_counts,
        "clean_exposure_count_distribution": exposure_counts,
        "settings": {
            "minimum_independent_visits": args.min_clean_epochs,
            "min_arm_sn": args.min_arm_sn,
            "max_vrad_err": args.max_vrad_err,
            "jitter_kms": args.jitter_kms,
            "include_backup": args.include_backup,
            "visit_aggregation_enabled": not args.disable_visit_aggregation,
            "maximum_visit_gap_hours": args.maximum_visit_gap_hours,
            "visit_error_floor_kms": args.visit_error_floor_kms,
        },
        "interpretation_boundary": (
            "Orbit-consistency scores are not compact-object classifications. Closely "
            "spaced exposures are aggregated by default to prevent pseudo-replication."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
