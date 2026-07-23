#!/usr/bin/env python3
"""Acquire and checksum the frozen public Dark-668 catalogues."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.dark668 import CATALOGUES, download_catalogue, load_catalogue, validate_catalogue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/dark668"))
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("outputs/dark668_catalogue_summary.json"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    files = []
    validations = []
    for spec in CATALOGUES:
        destination = args.output_dir / spec.filename
        files.append(
            download_catalogue(
                spec,
                destination,
                timeout=args.timeout,
                overwrite=args.overwrite,
            )
        )
        frame = load_catalogue(destination, spec.population)
        validations.append(validate_catalogue(frame, spec))

    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "catalogues": validations,
        "files": files,
        "promising_rows_total": sum(item["promising_rows"] for item in validations),
        "claim_boundary": (
            "This receipt validates frozen public inputs and aggregate counts only. "
            "It contains no source-level ranking or classification."
        ),
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
