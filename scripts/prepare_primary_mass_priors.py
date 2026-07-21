#!/usr/bin/env python3
"""Build triage-only primary-mass priors from Gaia GSP-Phot logg and radius."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.primary import draw_gspphot_primary_mass, summarize_primary_mass

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
    parser.add_argument("gaia", type=Path, help="Gaia v4 SB1 seed table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/primary_mass_priors.csv"),
    )
    parser.add_argument("--n-draws", type=int, default=20_000)
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--base-seed", type=int, default=20260722)
    parser.add_argument(
        "--max-fractional-68-width",
        type=float,
        default=1.0,
        help="mark broader priors as weak but retain them in output",
    )
    return parser.parse_args()


def _optional_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _stable_seed(base_seed: int, source_id: object, solution_id: object) -> int:
    payload = f"primary|{base_seed}|{source_id}|{solution_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def main() -> None:
    args = parse_args()
    if args.n_draws < 100:
        raise ValueError("n_draws must be at least 100")
    if args.max_rows < 1:
        raise ValueError("max_rows must be positive")
    if args.base_seed < 0:
        raise ValueError("base_seed must be non-negative")
    if args.max_fractional_68_width <= 0:
        raise ValueError("max_fractional_68_width must be positive")

    gaia = read_table(args.gaia)
    required = {
        "source_id",
        "solution_id",
        "logg_gspphot",
        "logg_gspphot_lower",
        "logg_gspphot_upper",
        "radius_gspphot",
        "radius_gspphot_lower",
        "radius_gspphot_upper",
    }
    missing = sorted(required - set(gaia.columns))
    if missing:
        raise KeyError(f"Gaia table is missing columns: {missing}")

    records: list[dict[str, object]] = []
    for _, row in gaia.head(args.max_rows).iterrows():
        source_id = row["source_id"]
        solution_id = row["solution_id"]
        record: dict[str, object] = {
            "source_id": source_id,
            "solution_id": solution_id,
            "status": "input_error",
            "error": "",
            "method": "gaia_gspphot_logg_radius_diagonal_proxy",
        }
        try:
            values = {
                "logg_median": _optional_float(row["logg_gspphot"]),
                "logg_lower": _optional_float(row["logg_gspphot_lower"]),
                "logg_upper": _optional_float(row["logg_gspphot_upper"]),
                "radius_median": _optional_float(row["radius_gspphot"]),
                "radius_lower": _optional_float(row["radius_gspphot_lower"]),
                "radius_upper": _optional_float(row["radius_gspphot_upper"]),
            }
            unavailable = [name for name, value in values.items() if value is None]
            if unavailable:
                raise ValueError(f"missing or non-finite inputs: {unavailable}")
            seed = _stable_seed(args.base_seed, source_id, solution_id)
            samples = draw_gspphot_primary_mass(
                **{name: float(value) for name, value in values.items()},
                n_draws=args.n_draws,
                random_seed=seed,
            )
            summary = summarize_primary_mass(samples)
            status = (
                "scored"
                if summary["fractional_68_width"] <= args.max_fractional_68_width
                else "weak_prior"
            )
            record.update(
                {
                    "status": status,
                    "random_seed": seed,
                    "primary_mass_solar": summary["primary_mass_solar"],
                    "primary_mass_error_solar": summary[
                        "primary_mass_error_solar"
                    ],
                    "primary_mass_lower_solar": summary[
                        "primary_mass_lower_solar"
                    ],
                    "primary_mass_upper_solar": summary[
                        "primary_mass_upper_solar"
                    ],
                    "fractional_68_width": summary["fractional_68_width"],
                    "interpretation": summary["interpretation"],
                }
            )
            for label, value in zip(
                _QUANTILE_LABELS,
                summary["mass_quantiles_solar"],
                strict=True,
            ):
                record[f"primary_mass_{label}_solar"] = value
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
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "input_rows": len(gaia),
        "rows_attempted": min(len(gaia), args.max_rows),
        "output_rows": len(result),
        "status_counts": status_counts,
        "settings": {
            "n_draws": args.n_draws,
            "max_rows": args.max_rows,
            "base_seed": args.base_seed,
            "max_fractional_68_width": args.max_fractional_68_width,
        },
        "interpretation_boundary": (
            "GSP-Phot assumes one star. These priors are triage-only and must be "
            "independently validated before compact-object interpretation."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
