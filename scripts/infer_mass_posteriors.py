#!/usr/bin/env python3
"""Generate robust minimum-mass and labelled inclination-sensitivity products."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.masses import draw_standard_sb1_products

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
    parser.add_argument("gaia", type=Path, help="Gaia SB1/SB1C seed table")
    parser.add_argument(
        "--primary-masses",
        type=Path,
        help=(
            "optional table keyed by source_id with primary_mass_solar and "
            "primary_mass_error_solar; omit when these columns are already in Gaia input"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/mass_posteriors.csv"),
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
    payload = f"{base_seed}|{source_id}|{solution_id}".encode("utf-8")
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
    }
    mass_values = product["companion_mass_quantiles_solar"]
    function_values = product["mass_function_quantiles_solar"]
    for label, mass_value, function_value in zip(
        _QUANTILE_LABELS,
        mass_values,
        function_values,
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
    required_gaia = {
        "source_id",
        "solution_id",
        "nss_solution_type",
        "period",
        "period_error",
        "semi_amplitude_primary",
        "semi_amplitude_primary_error",
    }
    missing_gaia = sorted(required_gaia - set(gaia.columns))
    if missing_gaia:
        raise KeyError(f"Gaia table is missing columns: {missing_gaia}")

    mass_input_sha256: str | None = None
    if args.primary_masses is not None:
        masses = read_table(args.primary_masses)
        required_mass = {
            "source_id",
            "primary_mass_solar",
            "primary_mass_error_solar",
        }
        missing_mass = sorted(required_mass - set(masses.columns))
        if missing_mass:
            raise KeyError(f"primary-mass table is missing columns: {missing_mass}")
        if masses["source_id"].duplicated().any():
            raise ValueError("primary-mass table contains duplicate source_id rows")
        gaia = gaia.merge(
            masses[list(required_mass)],
            on="source_id",
            how="left",
            validate="many_to_one",
        )
        mass_input_sha256 = sha256_file(args.primary_masses)

    required_mass_columns = {"primary_mass_solar", "primary_mass_error_solar"}
    missing_mass_columns = sorted(required_mass_columns - set(gaia.columns))
    if missing_mass_columns:
        raise KeyError(
            "primary-mass columns are unavailable; supply --primary-masses or add "
            f"them to the Gaia table: {missing_mass_columns}"
        )

    rows = gaia.head(args.max_rows).copy()
    records: list[dict[str, object]] = []
    for _, row in rows.iterrows():
        source_id = row["source_id"]
        solution_id = row["solution_id"]
        record: dict[str, object] = {
            "source_id": source_id,
            "solution_id": solution_id,
            "nss_solution_type": row["nss_solution_type"],
            "status": "input_error",
            "error": "",
            "orbital_covariance_mode": "diagonal_errors_only",
        }
        try:
            period = _optional_float(row["period"])
            period_error = _optional_float(row["period_error"])
            k1 = _optional_float(row["semi_amplitude_primary"])
            k1_error = _optional_float(row["semi_amplitude_primary_error"])
            primary_mass = _optional_float(row["primary_mass_solar"])
            primary_mass_error = _optional_float(row["primary_mass_error_solar"])
            solution_type = str(row["nss_solution_type"])
            eccentricity = _optional_float(row.get("eccentricity"))
            eccentricity_error = _optional_float(row.get("eccentricity_error"))
            if solution_type == "SB1C":
                eccentricity = 0.0
                eccentricity_error = 0.0

            values = {
                "period": period,
                "period_error": period_error,
                "k1": k1,
                "k1_error": k1_error,
                "eccentricity": eccentricity,
                "eccentricity_error": eccentricity_error,
                "primary_mass": primary_mass,
                "primary_mass_error": primary_mass_error,
            }
            unavailable = [name for name, value in values.items() if value is None]
            if unavailable:
                raise ValueError(f"missing or non-finite inputs: {unavailable}")
            assert period is not None
            assert period_error is not None
            assert k1 is not None
            assert k1_error is not None
            assert eccentricity is not None
            assert eccentricity_error is not None
            assert primary_mass is not None
            assert primary_mass_error is not None

            seed = _stable_seed(args.base_seed, source_id, solution_id)
            products = draw_standard_sb1_products(
                period_days=period,
                period_error_days=period_error,
                k1_kms=k1,
                k1_error_kms=k1_error,
                eccentricity=eccentricity,
                eccentricity_error=eccentricity_error,
                primary_mass_solar=primary_mass,
                primary_mass_error_solar=primary_mass_error,
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
                    "period_days": period,
                    "period_error_days": period_error,
                    "k1_kms": k1,
                    "k1_error_kms": k1_error,
                    "eccentricity": eccentricity,
                    "eccentricity_error": eccentricity_error,
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
        "primary_mass_input": (
            str(args.primary_masses) if args.primary_masses is not None else None
        ),
        "primary_mass_input_sha256": mass_input_sha256,
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "input_rows": len(gaia),
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
            "orbital_covariance_mode": "diagonal_errors_only",
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
