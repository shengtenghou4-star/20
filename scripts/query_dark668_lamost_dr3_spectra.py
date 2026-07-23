#!/usr/bin/env python3
"""Query exact Dark-668 Gaia DR3 IDs in LAMOST DR8 v2.0 stellar spectra."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.gaia import sha256_file
from hou_compact.lamost_dr3_spectra import (
    DR3SpectrumSpec,
    candidate_safe_dr3_spectrum_summary,
    normalize_dr3_source_ids,
    query_exact_dr3_spectra,
)
from hou_compact.lamost_openapi_sql import OpenAPISQLService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path, help="Dark-668 seed containing source_id")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_lamost_dr3_epochs.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_lamost_dr3_summary.json"),
    )
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v2.0")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--maxrec-per-batch", type=int, default=5000)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    if "source_id" not in candidates.columns:
        raise KeyError("candidate seed has no source_id column")
    source_ids = normalize_dr3_source_ids(candidates["source_id"])
    if len(source_ids) != len(candidates):
        raise ValueError("candidate seed contains duplicate Gaia DR3 source IDs")

    service = OpenAPISQLService(
        args.openapi_root,
        dr_version=args.dr_version,
        sub_version=args.sub_version,
        timeout=args.timeout,
    )
    spec = DR3SpectrumSpec()
    rows, receipts = query_exact_dr3_spectra(
        service,
        source_ids,
        spec=spec,
        batch_size=args.batch_size,
        maxrec_per_batch=args.maxrec_per_batch,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(args.output, index=False)

    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "candidate_input_sha256": sha256_file(args.candidates),
        "release": f"{args.dr_version}/{args.sub_version}",
        "sql_endpoint": service.endpoint,
        "transport": "bounded_openapi_sql_get",
        "identity_contract": (
            "Exact Gaia DR3 character-field equality in the DR8 v2.0 per-spectrum table."
        ),
        "summary": candidate_safe_dr3_spectrum_summary(
            len(source_ids), rows, receipts, spec=spec
        ),
        "query_receipts": [receipt.to_record() for receipt in receipts],
        "sql_receipts": [receipt.to_record() for receipt in service.receipts],
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": (
            "Never commit or upload plaintext source IDs, spectrum rows, RVs, or errors."
        ),
        "interpretation_boundary": (
            "The output is an exact per-spectrum follow-up dataset, not evidence of "
            "variability, binarity, or a compact companion."
        ),
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
