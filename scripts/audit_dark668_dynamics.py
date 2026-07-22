#!/usr/bin/env python3
"""Run the Dark-668 SB1 mass-function and geometry audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.dark668_dynamics import (
    DynamicalAuditConfig,
    candidate_safe_dynamical_summary,
    score_dynamical_consistency,
)
from hou_compact.gaia import sha256_file


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


def main() -> None:
    args = parse_args()
    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    kepler_scores = pd.read_csv(
        args.kepler_scores,
        dtype={"source_id": "string"},
    )
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
        "schema_version": "0.1",
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
