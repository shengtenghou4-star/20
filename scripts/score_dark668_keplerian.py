#!/usr/bin/env python3
"""Run full Keplerian follow-up fits on preselected Dark-668 RV targets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.dark668_kepler import (
    KeplerianConfig,
    candidate_safe_keplerian_summary,
    score_keplerian_candidates,
)
from hou_compact.gaia import sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("epochs", type=Path)
    parser.add_argument(
        "--circular-scores",
        type=Path,
        help="optional source-level period-prior scores used for preselection",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_keplerian_scores.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_keplerian_summary.json"),
    )
    parser.add_argument("--minimum-visits", type=int, default=7)
    parser.add_argument("--minimum-circular-delta-bic", type=float, default=6.0)
    parser.add_argument("--period-grid-size", type=int, default=192)
    parser.add_argument("--posterior-sigma-span", type=float, default=3.0)
    parser.add_argument("--maximum-eccentricity", type=float, default=0.95)
    parser.add_argument("--random-starts", type=int, default=32)
    parser.add_argument("--maximum-function-evaluations", type=int, default=4000)
    parser.add_argument("--minimum-arm-sn", type=float, default=2.0)
    parser.add_argument("--maximum-vrad-error-kms", type=float, default=20.0)
    parser.add_argument("--jitter-kms", type=float, default=0.0)
    parser.add_argument("--maximum-visit-gap-hours", type=float, default=2.0)
    parser.add_argument("--visit-error-floor-kms", type=float, default=0.0)
    parser.add_argument("--base-seed", type=int, default=20260723)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    epochs = pd.read_csv(args.epochs, dtype={"source_id": "string"})
    circular_scores = (
        pd.read_csv(args.circular_scores, dtype={"source_id": "string"})
        if args.circular_scores is not None
        else None
    )
    config = KeplerianConfig(
        minimum_independent_visits=args.minimum_visits,
        minimum_circular_delta_bic=args.minimum_circular_delta_bic,
        period_grid_size=args.period_grid_size,
        posterior_sigma_span=args.posterior_sigma_span,
        maximum_eccentricity=args.maximum_eccentricity,
        random_starts=args.random_starts,
        maximum_function_evaluations=args.maximum_function_evaluations,
        minimum_arm_sn=args.minimum_arm_sn,
        maximum_vrad_error_kms=args.maximum_vrad_error_kms,
        jitter_kms=args.jitter_kms,
        maximum_visit_gap_hours=args.maximum_visit_gap_hours,
        visit_error_floor_kms=args.visit_error_floor_kms,
        base_seed=args.base_seed,
    )
    scores = score_keplerian_candidates(
        candidates,
        epochs,
        circular_scores,
        config,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scores.to_csv(args.output, index=False)
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "candidate_input_sha256": sha256_file(args.candidates),
        "epoch_input_sha256": sha256_file(args.epochs),
        "circular_score_input_sha256": (
            sha256_file(args.circular_scores)
            if args.circular_scores is not None
            else None
        ),
        "configuration": config.to_record(),
        "summary": candidate_safe_keplerian_summary(scores),
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": "Never commit or upload the source-level Keplerian table.",
        "interpretation_boundary": (
            "A full Keplerian RV fit is a model comparison and follow-up product. It is "
            "not a compact-object classification or a novelty claim."
        ),
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
