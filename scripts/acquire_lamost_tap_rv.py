#!/usr/bin/env python3
"""Acquire exact per-spectrum LAMOST RV errors for an overlap epoch table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyvo

from hou_compact.gaia import sha256_file
from hou_compact.lamost_openapi import discover_openapi_contract
from hou_compact.lamost_tap_rv import (
    candidate_safe_tap_summary,
    discover_rv_table_specs,
    normalize_obsids,
    query_exact_obsids,
)


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
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--maxrec-per-batch", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    epochs = pd.read_csv(args.epochs, dtype={"obsid": "string"})
    if "obsid" not in epochs.columns:
        raise KeyError("epoch input has no obsid column")
    obsids = normalize_obsids(epochs["obsid"])
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
    service = pyvo.dal.TAPService(tap_url)
    specs = discover_rv_table_specs(service)
    rows, receipts = query_exact_obsids(
        service,
        specs,
        obsids,
        batch_size=args.batch_size,
        maxrec_per_batch=args.maxrec_per_batch,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(args.output, index=False)

    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "epoch_input_sha256": sha256_file(args.epochs),
        "release": f"{args.dr_version}/{args.sub_version}",
        "tap_url": tap_url,
        "batch_size": args.batch_size,
        "maxrec_per_batch": args.maxrec_per_batch,
        "summary": candidate_safe_tap_summary(len(obsids), rows, specs, receipts),
        "query_receipts": [receipt.to_record() for receipt in receipts],
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": "Never commit or upload the source-level TAP rows.",
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
