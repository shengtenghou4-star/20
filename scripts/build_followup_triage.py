#!/usr/bin/env python3
"""Merge Gaia, DESI orbit, primary-mass, and mass products into stage-gated triage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.triage import TriageConfig, triage_followup

_KEY = ["source_id", "solution_id"]


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
    parser.add_argument("orbit", type=Path)
    parser.add_argument("primary", type=Path)
    parser.add_argument("mass", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/followup_triage.csv"),
    )
    parser.add_argument("--min-period-confidence", type=float, default=0.99)
    parser.add_argument("--min-clean-desi-epochs", type=int, default=3)
    parser.add_argument("--min-phase-coverage", type=float, default=0.20)
    parser.add_argument("--min-delta-chi2", type=float, default=9.0)
    parser.add_argument("--max-orbit-reduced-chi2", type=float, default=5.0)
    parser.add_argument("--max-primary-fractional-width", type=float, default=0.75)
    parser.add_argument("--high-minimum-mass-q16", type=float, default=1.4)
    parser.add_argument("--very-high-minimum-mass-q16", type=float, default=3.0)
    return parser.parse_args()


def _require_unique(frame: pd.DataFrame, name: str) -> None:
    missing = sorted(set(_KEY) - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing keys: {missing}")
    if frame.duplicated(_KEY).any():
        raise ValueError(f"{name} contains duplicate source_id/solution_id rows")


def _rename_status_error(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    rename: dict[str, str] = {}
    if "status" in frame.columns:
        rename["status"] = f"{prefix}_status"
    if "error" in frame.columns:
        rename["error"] = f"{prefix}_error"
    return frame.rename(columns=rename)


def main() -> None:
    args = parse_args()
    gaia = read_table(args.gaia)
    orbit = _rename_status_error(read_table(args.orbit), "orbit")
    primary = _rename_status_error(read_table(args.primary), "primary")
    mass = _rename_status_error(read_table(args.mass), "mass")
    for frame, name in (
        (gaia, "gaia"),
        (orbit, "orbit"),
        (primary, "primary"),
        (mass, "mass"),
    ):
        _require_unique(frame, name)

    merged = gaia.merge(orbit, on=_KEY, how="left", validate="one_to_one")
    merged = merged.merge(primary, on=_KEY, how="left", validate="one_to_one")
    merged = merged.merge(mass, on=_KEY, how="left", validate="one_to_one")

    config = TriageConfig(
        min_period_confidence=args.min_period_confidence,
        min_clean_desi_epochs=args.min_clean_desi_epochs,
        min_phase_coverage=args.min_phase_coverage,
        min_delta_chi2=args.min_delta_chi2,
        max_orbit_reduced_chi2=args.max_orbit_reduced_chi2,
        max_primary_fractional_68_width=args.max_primary_fractional_width,
        high_minimum_mass_q16_solar=args.high_minimum_mass_q16,
        very_high_minimum_mass_q16_solar=args.very_high_minimum_mass_q16,
    )
    triage = pd.DataFrame(
        [triage_followup(row, config) for row in merged.to_dict(orient="records")]
    )
    output = pd.concat([merged.reset_index(drop=True), triage], axis=1)
    output = output.sort_values(
        ["triage_rank", "minimum_m2_q16_solar"],
        ascending=[False, False],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    stage_counts = {
        str(key): int(value) for key, value in output["triage_stage"].value_counts().items()
    }
    manifest = {
        "inputs": {
            "gaia": {"path": str(args.gaia), "sha256": sha256_file(args.gaia)},
            "orbit": {"path": str(args.orbit), "sha256": sha256_file(args.orbit)},
            "primary": {
                "path": str(args.primary),
                "sha256": sha256_file(args.primary),
            },
            "mass": {"path": str(args.mass), "sha256": sha256_file(args.mass)},
        },
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "output_rows": len(output),
        "stage_counts": stage_counts,
        "thresholds": {
            "min_period_confidence": config.min_period_confidence,
            "min_clean_desi_epochs": config.min_clean_desi_epochs,
            "min_phase_coverage": config.min_phase_coverage,
            "min_delta_chi2": config.min_delta_chi2,
            "max_orbit_reduced_chi2": config.max_orbit_reduced_chi2,
            "max_primary_fractional_68_width": (
                config.max_primary_fractional_68_width
            ),
            "high_minimum_mass_q16_solar": config.high_minimum_mass_q16_solar,
            "very_high_minimum_mass_q16_solar": (
                config.very_high_minimum_mass_q16_solar
            ),
        },
        "interpretation_boundary": (
            "Triage stages are follow-up priorities, not compact-object classifications."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
