#!/usr/bin/env python3
"""Discover first-party LAMOST TAP tables carrying per-spectrum RV errors.

This command queries TAP_SCHEMA only.  It never requests catalogue source rows,
identifiers, coordinates, spectra, or radial-velocity measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyvo

from hou_compact.lamost_openapi import discover_openapi_contract


TARGET_COLUMNS = (
    "obsid",
    "gaia_source_id",
    "rv",
    "rv_err",
    "snrg",
    "snri",
    "fibermask",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v1.0")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_tap_rv_schema.json"),
    )
    return parser.parse_args()


def _to_frame(result: Any) -> pd.DataFrame:
    table = result.to_table() if hasattr(result, "to_table") else result
    frame = table.to_pandas() if hasattr(table, "to_pandas") else pd.DataFrame(table)
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame


def main() -> None:
    args = parse_args()
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
    literals = ", ".join(f"'{column}'" for column in TARGET_COLUMNS)
    query = (
        "SELECT table_name, column_name, datatype, description "
        "FROM TAP_SCHEMA.columns "
        f"WHERE column_name IN ({literals})"
    )
    frame = _to_frame(service.run_sync(query, maxrec=10000))
    required = {"table_name", "column_name"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"TAP_SCHEMA result missing columns: {missing}")

    grouped: list[dict[str, object]] = []
    for table_name, group in frame.groupby("table_name", sort=True):
        columns = sorted({str(value).lower() for value in group["column_name"]})
        grouped.append(
            {
                "table_name": str(table_name),
                "columns": columns,
                "has_obsid": "obsid" in columns,
                "has_gaia_source_id": "gaia_source_id" in columns,
                "has_rv": "rv" in columns,
                "has_rv_err": "rv_err" in columns,
                "rv_scoring_ready": {"obsid", "rv", "rv_err"}.issubset(columns),
            }
        )
    scoring_tables = [row for row in grouped if row["rv_scoring_ready"]]
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "release": f"{args.dr_version}/{args.sub_version}",
        "tap_url": tap_url,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "matching_table_count": len(grouped),
        "rv_scoring_table_count": len(scoring_tables),
        "tables": grouped,
        "claim_boundary": (
            "TAP_SCHEMA metadata only. No catalogue rows, source identifiers, coordinates, "
            "spectra, radial velocities, or candidate classifications were requested."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not scoring_tables:
        raise RuntimeError("no TAP table exposes obsid, rv, and rv_err together")


if __name__ == "__main__":
    main()
