#!/usr/bin/env python3
"""Discover first-party LAMOST TAP tables carrying per-spectrum RV errors.

This command queries TAP_SCHEMA only. It never requests catalogue source rows,
identifiers, coordinates, spectra, or radial-velocity measurements. A bounded,
candidate-safe diagnostic is written even when endpoint discovery or schema access
fails, while the command still exits non-zero so transport failures cannot look green.
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
_CLAIM_BOUNDARY = (
    "TAP_SCHEMA metadata only. No catalogue rows, source identifiers, coordinates, "
    "spectra, radial velocities, or candidate classifications were requested."
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


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    print(text)


def _base_payload(args: argparse.Namespace, query: str) -> dict[str, object]:
    return {
        "schema_version": "0.2",
        "candidate_safe": True,
        "status": "failure",
        "release": f"{args.dr_version}/{args.sub_version}",
        "openapi_root": args.openapi_root,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "target_columns": sorted(TARGET_COLUMNS),
        "claim_boundary": _CLAIM_BOUNDARY,
    }


def main() -> None:
    args = parse_args()
    literals = ", ".join(f"'{column}'" for column in TARGET_COLUMNS)
    query = (
        "SELECT table_name, column_name, datatype, description "
        "FROM TAP_SCHEMA.columns "
        f"WHERE column_name IN ({literals})"
    )
    payload = _base_payload(args, query)
    try:
        contract = discover_openapi_contract(
            openapi_root=args.openapi_root,
            dr_version=args.dr_version,
            sub_version=args.sub_version,
            timeout=args.timeout,
        )
        tap_urls = [str(value) for value in contract.get("tap_urls", [])]
        payload["openapi_status"] = contract.get("status")
        payload["openapi_receipts"] = contract.get("receipts", {})
        payload["tap_urls"] = tap_urls
        if not tap_urls:
            raise RuntimeError("LAMOST OpenAPI returned no TAP URL")

        tap_url = tap_urls[0]
        payload["tap_url"] = tap_url
        service = pyvo.dal.TAPService(tap_url)
        frame = _to_frame(service.run_sync(query, maxrec=10_000))
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
        payload.update(
            {
                "matching_table_count": len(grouped),
                "rv_scoring_table_count": len(scoring_tables),
                "tables": grouped,
                "status": "pass" if scoring_tables else "no_scoring_table",
            }
        )
        _write(args.output, payload)
        if not scoring_tables:
            raise RuntimeError("no TAP table exposes obsid, rv, and rv_err together")
    except Exception as error:
        payload["status"] = (
            payload["status"]
            if payload.get("status") == "no_scoring_table"
            else "failure"
        )
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:2_000]
        _write(args.output, payload)
        raise


if __name__ == "__main__":
    main()
