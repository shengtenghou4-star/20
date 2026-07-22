#!/usr/bin/env python3
"""Run the Dark-668 SB1 mass-function and geometry audit."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from hou_compact.dark668_dynamics import (
    DynamicalAuditConfig,
    candidate_safe_dynamical_summary,
    score_dynamical_consistency,
)
from hou_compact.gaia import sha256_file

_FIT_COLUMNS = (
    "period_days",
    "semi_amplitude_kms",
    "eccentricity",
    "delta_bic_circular_minus_keplerian",
    "reduced_chi2",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("kepler_scores", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_dynamical_audit.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_dynamical_summary.json"),
    )
    parser.add_argument("--minimum-kepler-delta-bic", type=float, default=6.0)
    parser.add_argument("--maximum-reduced-chi2", type=float, default=5.0)
    parser.add_argument("--minimum-companion-mass-solar", type=float, default=3.0)
    parser.add_argument("--maximum-roche-fill-proxy", type=float, default=0.8)
    return parser.parse_args()


def _normalize_zero_result_schema(kepler_scores: pd.DataFrame) -> pd.DataFrame:
    if "status" not in kepler_scores.columns:
        raise KeyError("kepler score input has no status column")
    missing = [column for column in _FIT_COLUMNS if column not in kepler_scores.columns]
    if not missing:
        return kepler_scores
    if kepler_scores["status"].eq("scored").any():
        raise KeyError(f"scored Kepler rows are missing fit columns: {missing}")
    normalized = kepler_scores.copy()
    for column in missing:
        normalized[column] = math.nan
    return normalized


def main() -> None:
    args = parse_args()
    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    kepler_scores = pd.read_csv(
        args.kepler_scores,
        dtype={"source_id": "string"},
    )
    kepler_scores = _normalize_zero_result_schema(kepler_scores)
    config = DynamicalAuditConfig(
        minimum_kepler_delta_bic=args.minimum_kepler_delta_bic,
        maximum_reduced_chi2=args.maximum_reduced_chi2,
        minimum_companion_mass_solar=args.minimum_companion_mass_solar,
        maximum_roche_fill_proxy=args.maximum_roche_fill_proxy,
    )
    scores = score_dynamical_consistency(candidates, kepler_scores, config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scores.to_csv(args.output, index=False)

    payload = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "candidate_input_sha256": sha256_file(args.candidates),
        "kepler_input_sha256": sha256_file(args.kepler_scores),
        "configuration": config.to_record(),
        "summary": candidate_safe_dynamical_summary(scores),
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": (
            "Never commit or upload the plaintext source-level dynamical audit."
        ),
        "zero_result_policy": (
            "A Kepler table with no scored rows is a valid zero-result input; missing "
            "fit-only columns are padded with null values rather than treated as failure."
        ),
        "interpretation_boundary": (
            "The SB1 mass function and edge-on minimum mass are physical follow-up "
            "statistics, not compact-object classifications or novelty claims."
        ),
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
