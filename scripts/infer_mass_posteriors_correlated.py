#!/usr/bin/env python3
"""Generate Gaia-correlation-aware SB1/SB1C mass products for a pilot catalogue."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.correlated_masses import draw_standard_gaia_correlated_products
from hou_compact.gaia import sha256_file

_QUANTILE_LABELS = ("q01", "q05", "q16", "q50", "q84", "q95", "q99")


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path, help="Gaia v4 SB1/SB1C seed table")
    parser.add_argument(
        "--primary-masses",
        type=Path,
        required=True,
        help="table keyed by source_id and solution_id with primary-mass priors",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/mass_posteriors_correlated.csv"),
    )
    parser.add_argument("--n-draws", type=int, default=20_000)
    parser.add_argument("--max-rows", type=int, default=100)
    parser.add_argument("--base-seed", type=int, default=20260722)
    parser.add_argument("--minimum-isotropic-inclination-deg", type=float, default=0.0)
    return parser.parse_args()


def _optional_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _stable_seed(base_seed: int, source_id: object, solution_id: object) -> int:
    payload = f"correlated|{base_seed}|{source_id}|{solution_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def _flatten_product(prefix: str, product: dict[str, object]) -> dict[str, object]:
    quantiles = tuple(float(value) for value in product["quantiles"])
    if len(quantiles) != len(_QUANTILE_LABELS):
        raise ValueError("unexpected posterior quantile grid")
    flattened: dict[str, object] = {
        f"{prefix}_inclination_mode": product["inclination_mode"],
        f"{prefix}_n_draws": product["n_draws"],
        f"{prefix}_median_sin_inclination": product["median_sin_inclination"],
        f"{prefix}_interpretation": product["interpretation"],
        f"{prefix}_orbital_parameter_names_json": json.dumps(
            product["orbital_parameter_names"], separators=(",", ":")
        ),
        f"{prefix}_orbital_covariance_json": json.dumps(
            product["orbital_covariance"], separators=(",", ":")
        ),
        f"{prefix}_orbital_correlation_json": json.dumps(
            product["orbital_correlation"], separators=(",", ":")
        ),
        f"{prefix}_covariance_regularized": product["covariance_regularized"],
        f"{prefix}_physical_draw_acceptance_fraction": product[
            "physical_draw_acceptance_fraction"
        ],
    }
    for label, mass_value, function_value in zip(
        _QUANTILE_LABELS,
        product["companion_mass_quantiles_solar"],
        product["mass_function_quantiles_solar"],
        strict=True,
    ):
        flattened[f"{prefix}_m2_{label}_solar"] = mass_value
        flattened[f"{prefix}_mass_function_{label}_solar"] = function_value
    for key, value in product.items():
        if key.startswith("probability_m2_gt_"):
            flattened[f"{prefix}_{key}"] = value
    if "minimum_inclination_deg" in product:
        flattened[f"{prefix}_minimum_inclination_deg"] = product[
            "minimum_inclination_deg"
        ]
    return flattened


def main() -> None:
    args = parse_args()
    if args.n_draws < 100:
        raise ValueError("n_draws must be at least 100")
    if args.max_rows < 1:
        raise ValueError("max_rows must be positive")
    if args.base_seed < 0:
        raise ValueError("base_seed must be non-negative")

    gaia = read_table(args.gaia)
    primary = read_table(args.primary_masses)
    keys = ["source_id", "solution_id"]
    required_gaia = {
        *keys,
        "nss_solution_type",
        "period",
        "period_error",
        "semi_amplitude_primary",
        "semi_amplitude_primary_error",
        "corr_vec",
    }
    missing_gaia = sorted(required_gaia - set(gaia.columns))
    if missing_gaia:
        raise KeyError(f"Gaia table is missing columns: {missing_gaia}")
    required_primary = {
        *keys,
        "primary_mass_solar",
        "primary_mass_error_solar",
    }
    missing_primary = sorted(required_primary - set(primary.columns))
    if missing_primary:
        raise KeyError(f"primary-mass table is missing columns: {missing_primary}")
    if primary.duplicated(keys).any():
        raise ValueError("primary-mass table contains duplicate source/solution rows")

    merged = gaia.merge(
        primary[list(required_primary)],
        on=keys,
        how="left",
        validate="one_to_one",
    )
    rows = merged.head(args.max_rows).copy()
    records: list[dict[str, object]] = []
    for _, row in rows.iterrows():
        source_id = row["source_id"]
        solution_id = row["solution_id"]
        solution_type = str(row["nss_solution_type"])
        record: dict[str, object] = {
            "source_id": source_id,
            "solution_id": solution_id,
            "nss_solution_type": solution_type,
            "status": "input_error",
            "error": "",
            "orbital_covariance_mode": "gaia_corr_vec",
        }
        try:
            period = _optional_float(row["period"])
            period_error = _optional_float(row["period_error"])
            k1 = _optional_float(row["semi_amplitude_primary"])
            k1_error = _optional_float(row["semi_amplitude_primary_error"])
            primary_mass = _optional_float(row["primary_mass_solar"])
            primary_mass_error = _optional_float(row["primary_mass_error_solar"])
            eccentricity = _optional_float(row.get("eccentricity"))
            eccentricity_error = _optional_float(row.get("eccentricity_error"))
            if solution_type == "SB1C":
                eccentricity = None
                eccentricity_error = None
            required_values = {
                "period": period,
                "period_error": period_error,
                "k1": k1,
                "k1_error": k1_error,
                "primary_mass": primary_mass,
                "primary_mass_error": primary_mass_error,
            }
            if solution_type == "SB1":
                required_values.update(
                    {
                        "eccentricity": eccentricity,
                        "eccentricity_error": eccentricity_error,
                    }
                )
            unavailable = [
                name for name, value in required_values.items() if value is None
            ]
            if unavailable:
                raise ValueError(f"missing or non-finite inputs: {unavailable}")
            seed = _stable_seed(args.base_seed, source_id, solution_id)
            products = draw_standard_gaia_correlated_products(
                solution_type=solution_type,
                corr_vec=row["corr_vec"],
                period_days=float(period),
                period_error_days=float(period_error),
                k1_kms=float(k1),
                k1_error_kms=float(k1_error),
                eccentricity=eccentricity,
                eccentricity_error=eccentricity_error,
                primary_mass_solar=float(primary_mass),
                primary_mass_error_solar=float(primary_mass_error),
                n_draws=args.n_draws,
                minimum_isotropic_inclination_deg=(
                    args.minimum_isotropic_inclination_deg
                ),
                random_seed=seed,
            )
            record.update(
                {
                    "status": "scored",
                    "random_seed": seed,
                    "primary_mass_solar": primary_mass,
                    "primary_mass_error_solar": primary_mass_error,
                    **_flatten_product("minimum", products["minimum_mass"]),
                    **_flatten_product(
                        "isotropic_sensitivity",
                        products["isotropic_sensitivity"],
                    ),
                }
            )
        except (TypeError, ValueError, RuntimeError, KeyError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)

    result = pd.DataFrame.from_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value) for key, value in result["status"].value_counts().items()
    }
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "primary_mass_input": str(args.primary_masses),
        "primary_mass_input_sha256": sha256_file(args.primary_masses),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "input_rows": len(merged),
        "rows_attempted": len(rows),
        "output_rows": len(result),
        "status_counts": status_counts,
        "settings": {
            "n_draws": args.n_draws,
            "max_rows": args.max_rows,
            "base_seed": args.base_seed,
            "minimum_isotropic_inclination_deg": (
                args.minimum_isotropic_inclination_deg
            ),
            "orbital_covariance_mode": "gaia_corr_vec",
        },
        "interpretation_boundary": (
            "The edge-on product is a minimum-mass distribution. The isotropic product "
            "is a geometry-only sensitivity analysis and is not selection-function corrected."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
