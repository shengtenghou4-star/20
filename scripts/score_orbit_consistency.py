#!/usr/bin/env python3
"""Compare fixed Gaia SB1 orbit shapes with clean DESI epoch radial velocities."""

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
    parser.add_argument("epochs", type=Path, help="Extracted DESI epoch table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/orbit_consistency.csv"),
    )
    parser.add_argument("--min-clean-epochs", type=int, default=2)
    parser.add_argument("--min-arm-sn", type=float, default=2.0)
    parser.add_argument("--max-vrad-err", type=float, default=20.0)
    parser.add_argument("--jitter-kms", type=float, default=0.0)
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
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value) for key, value in result["status"].value_counts().items()
    }
    clean_epoch_counts = {
        str(key): int(value)
        for key, value in result["n_clean_epochs"].value_counts().sort_index().items()
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
        "clean_epoch_count_distribution": clean_epoch_counts,
        "settings": {
            "min_clean_epochs": args.min_clean_epochs,
            "min_arm_sn": args.min_arm_sn,
            "max_vrad_err": args.max_vrad_err,
            "jitter_kms": args.jitter_kms,
            "include_backup": args.include_backup,
        },
        "interpretation_boundary": (
            "Orbit-consistency scores are not compact-object classifications."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
