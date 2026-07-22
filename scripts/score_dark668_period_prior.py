#!/usr/bin/env python3
"""Score Dark-668 targets using independent RV visits and period priors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.dark668_rv import (
    PeriodPriorConfig,
    candidate_safe_period_summary,
    score_period_prior_candidates,
)
from hou_compact.gaia import sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument("epochs", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_period_prior_scores.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_period_prior_summary.json"),
    )
    parser.add_argument("--minimum-visits", type=int, default=5)
    parser.add_argument("--period-grid-size", type=int, default=192)
    parser.add_argument("--posterior-sigma-span", type=float, default=3.0)
    parser.add_argument("--minimum-arm-sn", type=float, default=2.0)
    parser.add_argument("--maximum-vrad-error-kms", type=float, default=20.0)
    parser.add_argument("--jitter-kms", type=float, default=0.0)
    parser.add_argument("--maximum-visit-gap-hours", type=float, default=2.0)
    parser.add_argument("--visit-error-floor-kms", type=float, default=0.0)
    parser.add_argument("--permutations", type=int, default=100)
    parser.add_argument("--base-seed", type=int, default=20260723)
    parser.add_argument(
        "--no-aggregate-visits",
        action="store_true",
        help="debug-only exposure-level scoring; independent-visit scoring is the default",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    epochs = pd.read_csv(args.epochs, dtype={"source_id": "string"})
    config = PeriodPriorConfig(
        minimum_independent_visits=args.minimum_visits,
        period_grid_size=args.period_grid_size,
        posterior_sigma_span=args.posterior_sigma_span,
        minimum_arm_sn=args.minimum_arm_sn,
        maximum_vrad_error_kms=args.maximum_vrad_error_kms,
        jitter_kms=args.jitter_kms,
        aggregate_visits=not args.no_aggregate_visits,
        maximum_visit_gap_hours=args.maximum_visit_gap_hours,
        visit_error_floor_kms=args.visit_error_floor_kms,
        permutation_repetitions=args.permutations,
        base_seed=args.base_seed,
    )
    scores = score_period_prior_candidates(candidates, epochs, config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scores.to_csv(args.output, index=False)

    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "candidate_input_sha256": sha256_file(args.candidates),
        "epoch_input_sha256": sha256_file(args.epochs),
        "configuration": config.to_record(),
        "summary": candidate_safe_period_summary(scores),
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": "Never commit or upload the source-level score table.",
        "interpretation_boundary": (
            "The circular period-prior model is a follow-up triage test, not a full orbit, "
            "mass measurement, compact-object classification, or novelty determination."
        ),
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
