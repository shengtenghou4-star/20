#!/usr/bin/env python3
"""Build triage-only primary-mass priors from Gaia FLAME or GSP-Phot."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.primary import (
    draw_flame_primary_mass,
    draw_gspphot_primary_mass,
    summarize_flame_primary_mass,
    summarize_primary_mass,
)

_QUANTILE_LABELS = ("q01", "q05", "q16", "q50", "q84", "q95", "q99")
_GSP_COLUMNS = (
    "logg_gspphot",
    "logg_gspphot_lower",
    "logg_gspphot_upper",
    "radius_gspphot",
    "radius_gspphot_lower",
    "radius_gspphot_upper",
)
_FLAME_COLUMNS = ("mass_flame", "mass_flame_lower", "mass_flame_upper")


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


def _flame_quality_class(value: object) -> int | None:
    text = str(value).strip()
    if text and text[0] in {"0", "1", "2"}:
        return int(text[0])
    return None


def _flame_summary(row: pd.Series, *, n_draws: int, random_seed: int) -> dict[str, object]:
    missing_columns = [name for name in _FLAME_COLUMNS if name not in row.index]
    if missing_columns:
        raise ValueError(f"FLAME columns unavailable: {missing_columns}")
    values = {
        "mass_median": _optional_float(row["mass_flame"]),
        "mass_lower": _optional_float(row["mass_flame_lower"]),
        "mass_upper": _optional_float(row["mass_flame_upper"]),
    }
    unavailable = [name for name, value in values.items() if value is None]
    if unavailable:
        raise ValueError(f"missing or non-finite FLAME inputs: {unavailable}")
    samples = draw_flame_primary_mass(
        **{name: float(value) for name, value in values.items()},
        n_draws=n_draws,
        random_seed=random_seed,
    )
    return summarize_flame_primary_mass(samples)


def _gspphot_summary(row: pd.Series, *, n_draws: int, random_seed: int) -> dict[str, object]:
    missing_columns = [name for name in _GSP_COLUMNS if name not in row.index]
    if missing_columns:
        raise ValueError(f"GSP-Phot columns unavailable: {missing_columns}")
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
        raise ValueError(f"missing or non-finite GSP-Phot inputs: {unavailable}")
    samples = draw_gspphot_primary_mass(
        **{name: float(value) for name, value in values.items()},
        n_draws=n_draws,
        random_seed=random_seed,
    )
    return summarize_primary_mass(samples)


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
    required = {"source_id", "solution_id"}
    missing = sorted(required - set(gaia.columns))
    if missing:
        raise KeyError(f"Gaia table is missing columns: {missing}")

    records: list[dict[str, object]] = []
    for _, row in gaia.head(args.max_rows).iterrows():
        source_id = row["source_id"]
        solution_id = row["solution_id"]
        seed = _stable_seed(args.base_seed, source_id, solution_id)
        flame_quality = _flame_quality_class(row.get("flags_flame"))
        record: dict[str, object] = {
            "source_id": source_id,
            "solution_id": solution_id,
            "status": "input_error",
            "error": "",
            "method": "",
            "random_seed": seed,
            "flags_flame": row.get("flags_flame"),
            "flame_quality_class": flame_quality,
            "fallback_reason": "",
        }
        summary: dict[str, object] | None = None
        flame_error = ""
        try:
            summary = _flame_summary(row, n_draws=args.n_draws, random_seed=seed)
        except (TypeError, ValueError, RuntimeError, KeyError) as error:
            flame_error = f"{type(error).__name__}: {error}"
            record["fallback_reason"] = flame_error

        if summary is None:
            try:
                summary = _gspphot_summary(row, n_draws=args.n_draws, random_seed=seed)
            except (TypeError, ValueError, RuntimeError, KeyError) as error:
                gsp_error = f"{type(error).__name__}: {error}"
                record["error"] = f"FLAME: {flame_error}; GSP-Phot: {gsp_error}"

        if summary is not None:
            broad = float(summary["fractional_68_width"]) > args.max_fractional_68_width
            poor_flame_quality = (
                summary["method"] == "gaia_flame_mass_percentile_prior"
                and flame_quality not in {0, 1}
            )
            status = "weak_prior" if broad or poor_flame_quality else "scored"
            record.update(
                {
                    "status": status,
                    "method": summary["method"],
                    "primary_mass_solar": summary["primary_mass_solar"],
                    "primary_mass_error_solar": summary["primary_mass_error_solar"],
                    "primary_mass_lower_solar": summary["primary_mass_lower_solar"],
                    "primary_mass_upper_solar": summary["primary_mass_upper_solar"],
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
        records.append(record)

    result = pd.DataFrame.from_records(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value) for key, value in result["status"].value_counts().items()
    }
    method_counts = {
        str(key): int(value) for key, value in result["method"].value_counts().items()
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
        "method_counts": method_counts,
        "settings": {
            "n_draws": args.n_draws,
            "max_rows": args.max_rows,
            "base_seed": args.base_seed,
            "max_fractional_68_width": args.max_fractional_68_width,
            "method_precedence": ["Gaia FLAME", "GSP-Phot logg-radius proxy"],
        },
        "interpretation_boundary": (
            "FLAME and GSP-Phot both rely on single-star assumptions. These priors are "
            "triage-only and must be independently validated before compact-object interpretation."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
