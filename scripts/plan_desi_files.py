#!/usr/bin/env python3
"""Build a deterministic DESI single-epoch file plan from a Gaia seed table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from astropy.table import Table

from hou_compact.desi import DEFAULT_SURVEY_PROGRAMS, plan_single_epoch_files, write_file_plan
from hou_compact.gaia import sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="Gaia seed table readable by Astropy")
    parser.add_argument("--output", type=Path, default=Path("outputs/desi_single_epoch_plan.csv"))
    parser.add_argument(
        "--survey-program",
        action="append",
        default=[],
        metavar="SURVEY:PROGRAM",
        help="repeat to override the default main:bright,dark,backup plan",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    table = Table.read(args.input)
    if "source_id" not in table.colnames:
        raise KeyError("input table has no source_id column")
    pairs = DEFAULT_SURVEY_PROGRAMS
    if args.survey_program:
        parsed = []
        for item in args.survey_program:
            survey, separator, program = item.partition(":")
            if not separator or not survey or not program:
                raise ValueError(f"invalid SURVEY:PROGRAM value: {item!r}")
            parsed.append((survey, program))
        pairs = tuple(parsed)
    plan = plan_single_epoch_files(table["source_id"], pairs)
    frame = write_file_plan(plan, args.output)
    manifest = {
        "input": str(args.input),
        "input_sha256": sha256_file(args.input),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "source_rows": len(table),
        "unique_level6_healpix": int(frame["healpix"].nunique()) if not frame.empty else 0,
        "planned_files": len(frame),
        "survey_programs": [list(pair) for pair in sorted(set(pairs))],
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
