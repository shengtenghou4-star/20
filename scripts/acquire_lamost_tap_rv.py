#!/usr/bin/env python3
"""Acquire exact per-spectrum LAMOST RV errors for an overlap epoch table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from hou_compact.gaia import sha256_file
from hou_compact.lamost_openapi import discover_openapi_contract
from hou_compact.lamost_tap_get import TapGetService
from hou_compact.lamost_tap_rv import (
    candidate_safe_tap_summary,
    discover_rv_table_specs,
    normalize_obsids,
    query_exact_obsids,
)

_EMPTY_COLUMNS = [
    "obsid",
    "rv",
    "rv_err",
    "snrg",
    "snri",
    "class",
    "subclass",
    "fibermask",
    "gaia_source_id",
    "tap_table",
    "tap_table_priority",
    "matched_table_count",
    "tap_rv_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("epochs", type=Path, help="LAMOST MEC overlap containing obsid")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_lamost_tap_rv.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_lamost_tap_rv_summary.json"),
    )
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v1.0")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--maxrec-per-batch", type=int, default=250)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def _read_obsids(path: Path) -> list[int]:
    try:
        epochs = pd.read_csv(path, dtype={"obsid": "string"})
    except pd.errors.EmptyDataError:
        return []
    if "obsid" not in epochs.columns:
        if epochs.empty:
            return []
        raise KeyError("epoch input has no obsid column")
    return normalize_obsids(epochs["obsid"])


def _write_outputs(
    args: argparse.Namespace,
    rows: pd.DataFrame,
    payload: dict[str, Any],
) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(args.output, index=False)
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    args = parse_args()
    obsids = _read_obsids(args.epochs)
    if not obsids:
        rows = pd.DataFrame(columns=_EMPTY_COLUMNS)
        payload = {
            "schema_version": "0.3",
            "candidate_safe": True,
            "epoch_input_sha256": sha256_file(args.epochs),
            "release": f"{args.dr_version}/{args.sub_version}",
            "transport": "skipped_no_target_obsids",
            "batch_size": args.batch_size,
            "maxrec_per_batch": args.maxrec_per_batch,
            "summary": candidate_safe_tap_summary(0, rows, [], []),
            "query_receipts": [],
            "transport_receipts": [],
            "source_level_output_written": True,
            "source_level_output_path": str(args.output),
            "public_commit_policy": "Never commit or upload source-level TAP rows.",
            "zero_overlap_policy": (
                "No LAMOST spectrum IDs were supplied, so zero RV rows is a valid "
                "scientific result and no external TAP request was made."
            ),
        }
        _write_outputs(args, rows, payload)
        return

    contract = discover_openapi_contract(
        openapi_root=args.openapi_root,
        dr_version=args.dr_version,
        sub_version=args.sub_version,
        timeout=args.timeout,
    )
    tap_urls = [str(value) for value in contract.get("tap_urls", [])]
    if not tap_urls:
        raise RuntimeError("LAMOST OpenAPI returned no TAP URL")
    tap_url = tap_urls[0]
    service = TapGetService(tap_url, timeout=args.timeout)
    specs = discover_rv_table_specs(service)
    rows, receipts = query_exact_obsids(
        service,
        specs,
        obsids,
        batch_size=args.batch_size,
        maxrec_per_batch=args.maxrec_per_batch,
    )
    payload = {
        "schema_version": "0.3",
        "candidate_safe": True,
        "epoch_input_sha256": sha256_file(args.epochs),
        "release": f"{args.dr_version}/{args.sub_version}",
        "tap_url": tap_url,
        "transport": "bounded_https_get",
        "batch_size": args.batch_size,
        "maxrec_per_batch": args.maxrec_per_batch,
        "summary": candidate_safe_tap_summary(len(obsids), rows, specs, receipts),
        "query_receipts": [receipt.to_record() for receipt in receipts],
        "transport_receipts": [receipt.to_record() for receipt in service.receipts],
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": "Never commit or upload source-level TAP rows.",
    }
    _write_outputs(args, rows, payload)


if __name__ == "__main__":
    main()
