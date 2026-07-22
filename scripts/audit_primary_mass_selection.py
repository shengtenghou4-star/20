#!/usr/bin/env python3
"""Quantify whether primary-mass availability selects a biased Gaia subset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.selection_bias import (
    audit_numeric_selection,
    primary_mass_status_mask,
    quantile_bin_selection_rates,
)

_KEY = ["source_id", "solution_id"]
_DEFAULT_FIELDS = (
    "phot_g_mean_mag",
    "bp_rp",
    "parallax_over_error",
    "period",
    "semi_amplitude_primary",
    "significance",
    "rv_n_good_obs_primary",
    "teff_gspphot",
    "logg_gspphot",
    "radius_gspphot",
)


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path)
    parser.add_argument("primary", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/primary_mass_selection_audit.json"),
    )
    parser.add_argument(
        "--bins-output",
        type=Path,
        help="aggregate quantile-bin table; defaults beside --output",
    )
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        help="repeat to override the frozen default numeric field list",
    )
    return parser.parse_args()


def _require_unique(frame: pd.DataFrame, name: str) -> None:
    missing = sorted(set(_KEY) - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing keys: {missing}")
    if frame.duplicated(_KEY).any():
        raise ValueError(f"{name} contains duplicate source_id/solution_id rows")


def main() -> None:
    args = parse_args()
    gaia = read_table(args.gaia)
    primary = read_table(args.primary)
    _require_unique(gaia, "gaia")
    _require_unique(primary, "primary")
    if "status" not in primary.columns:
        raise KeyError("primary table has no status column")

    merged = gaia.merge(
        primary[_KEY + ["status", "error"]],
        on=_KEY,
        how="left",
        validate="one_to_one",
        suffixes=("", "_primary"),
    )
    scored = primary_mass_status_mask(merged)
    fields = tuple(args.field) if args.field else _DEFAULT_FIELDS
    missing_fields = sorted(set(fields) - set(merged.columns))
    if missing_fields:
        raise KeyError(f"Gaia input is missing audit fields: {missing_fields}")

    audits = [
        audit_numeric_selection(merged, field=field, scored_mask=scored).to_record()
        for field in fields
    ]
    bin_frames = [
        quantile_bin_selection_rates(
            merged,
            field=field,
            scored_mask=scored,
        )
        for field in fields
    ]
    bins = pd.concat(bin_frames, ignore_index=True) if bin_frames else pd.DataFrame()
    bins_output = args.bins_output or args.output.with_name(
        args.output.stem + ".bins.csv"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bins_output.parent.mkdir(parents=True, exist_ok=True)
    bins.to_csv(bins_output, index=False)

    status_counts = {
        str(key): int(value)
        for key, value in merged["status"].fillna("missing_product_row").value_counts().items()
    }
    error_counts = {
        str(key): int(value)
        for key, value in merged.loc[~scored, "error"]
        .fillna("missing_error_text")
        .astype(str)
        .value_counts()
        .head(25)
        .items()
    }
    large_or_moderate = [
        item["field"]
        for item in audits
        if item["interpretation"]
        in {"large_distribution_shift", "moderate_distribution_shift"}
    ]
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "primary_input": str(args.primary),
        "primary_input_sha256": sha256_file(args.primary),
        "cohort_rows": len(merged),
        "mass_scored_rows": int(scored.sum()),
        "mass_unscored_rows": int((~scored).sum()),
        "mass_scored_fraction": float(scored.mean()),
        "primary_status_counts": status_counts,
        "top_unscored_error_counts": error_counts,
        "numeric_field_audits": audits,
        "moderate_or_large_shift_fields": large_or_moderate,
        "bins_output": str(bins_output),
        "bins_output_sha256": sha256_file(bins_output),
        "interpretation_boundary": (
            "This audit quantifies selection into the primary-mass-scored subset. "
            "Distribution differences do not identify the causal missingness mechanism, "
            "and unscored rows are not astrophysical rejections. No source identifiers "
            "or candidate-level values are emitted."
        ),
    }
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
