#!/usr/bin/env python3
"""Create a novelty-sensitive Dark-668 follow-up queue and a safe aggregate receipt."""

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/dark668"))
    parser.add_argument(
        "--sensitive-output",
        type=Path,
        default=Path("outputs/private/dark668_ranked.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_rank_summary.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frames = []
    validations = []
    for spec in CATALOGUES:
        frame = load_catalogue(args.input_dir / spec.filename, spec.population)
        validations.append(validate_catalogue(frame, spec))
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    ranked = rank_promising_targets(combined)
    if len(ranked) != sum(spec.expected_promising_count for spec in CATALOGUES):
        raise RuntimeError("combined promising count drift")

    args.sensitive_output.parent.mkdir(parents=True, exist_ok=True)
    ranked.to_csv(args.sensitive_output, index=False)

    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "catalogue_validation": validations,
        "ranking": candidate_safe_summary(ranked),
        "sensitive_output_written": True,
        "sensitive_output_path": str(args.sensitive_output),
        "public_commit_policy": "Never commit the source-level ranked output.",
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
