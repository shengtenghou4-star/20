#!/usr/bin/env python3
"""Run candidate-safe phase-scramble and RV-offset orbit controls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.negative_controls import (
    OrbitScoreThresholds,
    audit_systemic_offset_invariance,
    run_phase_scramble_control,
)


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
    parser.add_argument("epochs", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/orbit_phase_scramble_control.csv"),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="candidate-safe JSON summary; defaults beside --output",
    )
    parser.add_argument("--repetitions", type=int, default=100)
    parser.add_argument("--base-seed", type=int, default=20260722)
    parser.add_argument("--min-clean-visits", type=int, default=3)
    parser.add_argument("--min-phase-coverage", type=float, default=0.20)
    parser.add_argument("--max-orbit-reduced-chi2", type=float, default=5.0)
    parser.add_argument("--minimum-arm-sn", type=float, default=2.0)
    parser.add_argument("--maximum-vrad-error", type=float, default=20.0)
    parser.add_argument("--jitter-kms", type=float, default=0.0)
    parser.add_argument("--maximum-visit-gap-hours", type=float, default=2.0)
    parser.add_argument("--visit-error-floor-kms", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gaia = read_table(args.gaia)
    epochs = read_table(args.epochs)
    thresholds = OrbitScoreThresholds(
        maximum_reduced_chi2=args.max_orbit_reduced_chi2,
        minimum_phase_coverage=args.min_phase_coverage,
        minimum_clean_visits=args.min_clean_visits,
    )
    scorer_kwargs = {
        "min_clean_epochs": 2,
        "min_arm_sn": args.minimum_arm_sn,
        "max_vrad_err": args.maximum_vrad_error,
        "jitter_kms": args.jitter_kms,
        "aggregate_visits": True,
        "maximum_visit_gap_hours": args.maximum_visit_gap_hours,
        "visit_error_floor_kms": args.visit_error_floor_kms,
    }
    null, phase_summary = run_phase_scramble_control(
        gaia,
        epochs,
        repetitions=args.repetitions,
        base_seed=args.base_seed,
        thresholds=thresholds,
        scorer_kwargs=scorer_kwargs,
    )
    offset_summary = audit_systemic_offset_invariance(
        gaia,
        epochs,
        base_seed=args.base_seed,
        scorer_kwargs=scorer_kwargs,
    )

    summary_output = args.summary_output or args.output.with_suffix(
        args.output.suffix + ".summary.json"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    null.to_csv(args.output, index=False)
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "epoch_input": str(args.epochs),
        "epoch_input_sha256": sha256_file(args.epochs),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "phase_scramble": phase_summary,
        "systemic_offset_invariance": offset_summary,
        "scorer_settings": scorer_kwargs,
        "interpretation_boundary": (
            "These controls test chance phase alignment and additive velocity-offset "
            "invariance. They contain no source-level results and do not classify objects."
        ),
    }
    summary_output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
