#!/usr/bin/env python3
"""Audit whether Gaia radius/orbit/mass summaries fit inside the primary Roche lobe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.roche import deterministic_roche_seed, infer_roche_geometry_posterior

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
    parser.add_argument("primary", type=Path)
    parser.add_argument("mass", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/roche_geometry_audit.csv"),
    )
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--n-draws", type=int, default=20_000)
    parser.add_argument("--base-seed", type=int, default=20260722)
    return parser.parse_args()


def _require_unique(frame: pd.DataFrame, name: str) -> None:
    missing = sorted(set(_KEY) - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing keys: {missing}")
    if frame.duplicated(_KEY).any():
        raise ValueError(f"{name} contains duplicate source_id/solution_id rows")


def _finite(row: pd.Series, name: str) -> float:
    value = float(row[name])
    if not np.isfinite(value):
        raise ValueError(f"missing or non-finite {name}")
    return value


def main() -> None:
    args = parse_args()
    if args.max_rows is not None and args.max_rows < 1:
        raise ValueError("max_rows must be positive")
    if args.n_draws < 100:
        raise ValueError("n_draws must be at least 100")

    gaia = read_table(args.gaia)
    primary = read_table(args.primary)
    mass = read_table(args.mass)
    for frame, name in ((gaia, "gaia"), (primary, "primary"), (mass, "mass")):
        _require_unique(frame, name)

    gaia_columns = _KEY + [
        "period",
        "period_error",
        "eccentricity",
        "eccentricity_error",
        "radius_gspphot",
        "radius_gspphot_lower",
        "radius_gspphot_upper",
    ]
    missing_gaia = sorted(set(gaia_columns) - set(gaia.columns))
    if missing_gaia:
        raise KeyError(f"gaia is missing Roche inputs: {missing_gaia}")
    primary_columns = _KEY + [
        "status",
        "primary_mass_q16_solar",
        "primary_mass_q50_solar",
        "primary_mass_q84_solar",
    ]
    missing_primary = sorted(set(primary_columns) - set(primary.columns))
    if missing_primary:
        raise KeyError(f"primary is missing Roche inputs: {missing_primary}")
    mass_columns = _KEY + [
        "status",
        "minimum_m2_q16_solar",
        "minimum_m2_q50_solar",
        "minimum_m2_q84_solar",
    ]
    missing_mass = sorted(set(mass_columns) - set(mass.columns))
    if missing_mass:
        raise KeyError(f"mass is missing Roche inputs: {missing_mass}")

    primary = primary[primary_columns].rename(columns={"status": "primary_status"})
    mass = mass[mass_columns].rename(columns={"status": "mass_status"})
    merged = gaia[gaia_columns].merge(
        primary,
        on=_KEY,
        how="left",
        validate="one_to_one",
    ).merge(
        mass,
        on=_KEY,
        how="left",
        validate="one_to_one",
    )
    if args.max_rows is not None:
        merged = merged.head(args.max_rows).copy()

    records: list[dict[str, object]] = []
    for _, row in merged.iterrows():
        record: dict[str, object] = {
            "source_id": int(row["source_id"]),
            "solution_id": int(row["solution_id"]),
            "status": "input_error",
            "error": "",
        }
        try:
            if row.get("primary_status") not in {"scored", "weak_prior"}:
                raise ValueError("primary-mass product is not scored")
            if row.get("mass_status") != "scored":
                raise ValueError("companion-mass product is not scored")
            seed = deterministic_roche_seed(
                int(row["source_id"]),
                int(row["solution_id"]),
                args.base_seed,
            )
            posterior = infer_roche_geometry_posterior(
                period_days=_finite(row, "period"),
                period_error_days=_finite(row, "period_error"),
                eccentricity=_finite(row, "eccentricity"),
                eccentricity_error=_finite(row, "eccentricity_error"),
                primary_mass_q16_solar=_finite(row, "primary_mass_q16_solar"),
                primary_mass_q50_solar=_finite(row, "primary_mass_q50_solar"),
                primary_mass_q84_solar=_finite(row, "primary_mass_q84_solar"),
                companion_mass_q16_solar=_finite(row, "minimum_m2_q16_solar"),
                companion_mass_q50_solar=_finite(row, "minimum_m2_q50_solar"),
                companion_mass_q84_solar=_finite(row, "minimum_m2_q84_solar"),
                primary_radius_q16_solar=_finite(row, "radius_gspphot_lower"),
                primary_radius_q50_solar=_finite(row, "radius_gspphot"),
                primary_radius_q84_solar=_finite(row, "radius_gspphot_upper"),
                n_draws=args.n_draws,
                random_seed=seed,
            )
            record.update(posterior.to_record())
            record["random_seed"] = seed
        except (TypeError, ValueError, RuntimeError, KeyError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)

    output = pd.DataFrame.from_records(records)
    output = output.sort_values(_KEY, kind="stable").reset_index(drop=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value) for key, value in output["status"].value_counts().items()
    }
    manifest = {
        "gaia": {"path": str(args.gaia), "sha256": sha256_file(args.gaia)},
        "primary": {"path": str(args.primary), "sha256": sha256_file(args.primary)},
        "mass": {"path": str(args.mass), "sha256": sha256_file(args.mass)},
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "output_rows": len(output),
        "status_counts": status_counts,
        "settings": {
            "max_rows": args.max_rows,
            "n_draws": args.n_draws,
            "base_seed": args.base_seed,
            "roche_epoch": "periastron",
        },
        "interpretation_boundary": (
            "Roche-geometry inconsistency challenges the adopted Gaia orbit and/or "
            "single-star stellar parameters. Detached geometry does not establish an "
            "unseen compact companion."
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
