#!/usr/bin/env python3
"""Prepare a source-level Dark-668 seed for private/ephemeral follow-up work."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.dark668 import (
    CATALOGUES,
    candidate_safe_summary,
    load_catalogue,
    rank_promising_targets,
    validate_catalogue,
)


SAFE_SEED_COLUMNS = (
    "source_id",
    "ra",
    "dec",
    "parallax",
    "parallax_error",
    "phot_g_mean_mag",
    "mass",
    "radius",
    "population",
    "priority_rank",
    "followup_score",
    "mass_lower_bound_proxy",
    "mass_significance",
    "fit_companion_mass",
    "fit_companion_mass_errup",
    "fit_companion_mass_errlow",
    "fit_period",
    "fit_period_errup",
    "fit_period_errlow",
    "rv_nb_transits",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/dark668"))
    parser.add_argument(
        "--population",
        choices=("RGB", "MS", "all"),
        default="all",
        help="subset written to the source-level seed",
    )
    parser.add_argument("--top", type=int, help="optional top-N cut after deterministic ranking")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_seed.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_seed_summary.json"),
    )
    return parser.parse_args()


def build_seed(input_dir: Path, population: str, top: int | None) -> tuple[pd.DataFrame, dict]:
    if top is not None and top <= 0:
        raise ValueError("--top must be positive")

    frames: list[pd.DataFrame] = []
    validations: list[dict[str, object]] = []
    for spec in CATALOGUES:
        frame = load_catalogue(input_dir / spec.filename, spec.population)
        validations.append(validate_catalogue(frame, spec))
        frames.append(frame)

    ranked = rank_promising_targets(pd.concat(frames, ignore_index=True, sort=False))
    if len(ranked) != sum(spec.expected_promising_count for spec in CATALOGUES):
        raise RuntimeError("combined promising count drift")
    if population != "all":
        ranked = ranked.loc[ranked["population"].eq(population)].copy()
    if top is not None:
        ranked = ranked.head(top).copy()

    missing = sorted(set(SAFE_SEED_COLUMNS) - set(ranked.columns))
    if missing:
        raise KeyError(f"ranked catalogue missing seed columns: {missing}")
    seed = ranked.loc[:, SAFE_SEED_COLUMNS].copy()
    if seed["source_id"].duplicated().any():
        raise ValueError("prepared seed contains duplicate source_id rows")

    summary = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "population_request": population,
        "top_request": top,
        "catalogue_validation": validations,
        "seed": candidate_safe_summary(ranked),
        "source_level_output_written": True,
        "public_commit_policy": "Never commit or upload the source-level seed.",
        "private_schema_note": (
            "The encrypted seed carries primary-star mass and radius for downstream "
            "mass-function and Roche-geometry audits; neither value is exposed publicly."
        ),
        "claim_boundary": (
            "The seed is a deterministic follow-up queue. It does not classify any source "
            "or establish novelty, binarity, or a compact companion."
        ),
    }
    return seed, summary


def main() -> None:
    args = parse_args()
    seed, summary = build_seed(args.input_dir, args.population, args.top)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    seed.to_csv(args.output, index=False)
    summary["source_level_output_path"] = str(args.output)
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
