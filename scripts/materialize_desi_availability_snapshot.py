#!/usr/bin/env python3
"""Materialize the immutable DESI availability cache for the frozen v7/v9 plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.desi_availability_snapshot import (
    SNAPSHOT_COHORT_ROWS,
    SNAPSHOT_EXPECTED_URLS,
    SNAPSHOT_RUN_ID,
    SNAPSHOT_SOURCE_PROBE_SHA256,
    iter_snapshot_files,
    validate_snapshot,
)
from hou_compact.gaia import sha256_file

_CANONICAL_PLAN_SHA256 = "b6557abd89c6fef65f1a4f666ef711858e763b00f33665100d71509d635b387c"
_CANONICAL_UNIQUE_HEALPIX = 4033


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "plan",
        type=Path,
        help="deterministic DESI plan produced from the frozen Gaia v7/v9 cohort",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_probe_from_snapshot.csv"),
    )
    parser.add_argument("--include-backup", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_snapshot()
    plan_sha256 = sha256_file(args.plan)
    if plan_sha256 != _CANONICAL_PLAN_SHA256:
        raise ValueError(
            "DESI plan is not the frozen v7/v9 cohort plan: "
            f"{plan_sha256} != {_CANONICAL_PLAN_SHA256}"
        )

    plan = pd.read_csv(args.plan)
    required = {"healpix", "survey", "program", "url"}
    missing = sorted(required - set(plan.columns))
    if missing:
        raise KeyError(f"plan is missing columns: {missing}")
    if len(plan) != SNAPSHOT_EXPECTED_URLS:
        raise ValueError(
            f"plan row count mismatch: {len(plan)} != {SNAPSHOT_EXPECTED_URLS}"
        )
    unique_healpix = int(pd.to_numeric(plan["healpix"], errors="raise").nunique())
    if unique_healpix != _CANONICAL_UNIQUE_HEALPIX:
        raise ValueError(
            f"plan HEALPix count mismatch: {unique_healpix} != {_CANONICAL_UNIQUE_HEALPIX}"
        )

    planned_urls = set(plan["url"].astype(str))
    snapshot_files = iter_snapshot_files(include_backup=args.include_backup)
    missing_urls = [item.url for item in snapshot_files if item.url not in planned_urls]
    if missing_urls:
        raise ValueError(
            f"snapshot contains {len(missing_urls)} URLs absent from the canonical plan"
        )

    output = pd.DataFrame(
        {
            "healpix": [item.healpix for item in snapshot_files],
            "parent": [item.healpix // 100 for item in snapshot_files],
            "survey": [item.survey for item in snapshot_files],
            "program": [item.program for item in snapshot_files],
            "url": [item.url for item in snapshot_files],
            "http_status": 200,
            "exists": True,
            "availability_source": "immutable_relay_probe_snapshot",
            "availability_snapshot_run_id": SNAPSHOT_RUN_ID,
            "availability_source_probe_sha256": SNAPSHOT_SOURCE_PROBE_SHA256,
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    manifest = {
        "plan": str(args.plan),
        "plan_sha256": plan_sha256,
        "canonical_plan_sha256": _CANONICAL_PLAN_SHA256,
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "cohort_rows": SNAPSHOT_COHORT_ROWS,
        "canonical_plan_rows": SNAPSHOT_EXPECTED_URLS,
        "canonical_unique_healpix": _CANONICAL_UNIQUE_HEALPIX,
        "snapshot_rows": len(output),
        "include_backup": args.include_backup,
        "program_counts": {
            str(key): int(value)
            for key, value in output["program"].value_counts().items()
        },
        "source_probe_sha256": SNAPSHOT_SOURCE_PROBE_SHA256,
        "source_relay_run_id": SNAPSHOT_RUN_ID,
        "interpretation_boundary": (
            "This cache contains public DESI file availability only. It contains no Gaia "
            "source IDs, radial velocities, mass products, or candidate classifications."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
