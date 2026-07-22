#!/usr/bin/env python3
"""Discover public LAMOST DR8 catalogue tables through China-VO TAP metadata."""

from __future__ import annotations

import argparse
import hashlib
import json

import pyvo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tap-url",
        default="https://tap.china-vo.org",
        help="China-VO TAP service root",
    )
    parser.add_argument("--max-tables", type=int, default=10_000)
    return parser.parse_args()


def _text(value: object) -> str:
    return "" if value is None else str(value)


def main() -> None:
    args = parse_args()
    if args.max_tables < 1:
        raise ValueError("max_tables must be positive")
    table_query = (
        "SELECT TOP {maximum} schema_name, table_name, description "
        "FROM TAP_SCHEMA.tables ORDER BY schema_name, table_name"
    ).format(maximum=args.max_tables)
    service = pyvo.dal.TAPService(args.tap_url)
    tables = (
        service.run_sync(
            table_query,
            maxrec=args.max_tables + 1,
        )
        .to_table()
        .to_pandas()
    )
    tables.columns = [str(column).lower() for column in tables.columns]
    if len(tables) >= args.max_tables:
        raise RuntimeError(
            "TAP table discovery reached max_tables and may be truncated"
        )

    haystack = (
        tables["schema_name"].map(_text)
        + " "
        + tables["table_name"].map(_text)
        + " "
        + tables["description"].map(_text)
    ).str.lower()
    candidates = tables.loc[
        haystack.str.contains("lamost")
        & (
            haystack.str.contains("dr8")
            | haystack.str.contains("multiple")
            | haystack.str.contains("epoch")
        )
    ].copy()
    if candidates.empty:
        raise RuntimeError(
            "no LAMOST DR8/multiple-epoch TAP tables were discovered"
        )
    candidates = candidates.sort_values(
        ["schema_name", "table_name"],
        kind="stable",
    ).reset_index(drop=True)

    candidate_names = candidates["table_name"].astype(str).tolist()
    literals = ",".join(
        "'" + name.replace("'", "''") + "'" for name in candidate_names
    )
    column_query = (
        "SELECT table_name, column_name, datatype, description "
        "FROM TAP_SCHEMA.columns "
        f"WHERE table_name IN ({literals}) "
        "ORDER BY table_name, column_index"
    )
    columns = (
        service.run_sync(column_query, maxrec=20_000)
        .to_table()
        .to_pandas()
    )
    columns.columns = [str(column).lower() for column in columns.columns]
    required_names = {
        "gaia_source_id",
        "obs_number",
        "obsid_list",
        "midmjm_list",
        "rv_list",
        "rv_err",
    }
    column_summary: dict[str, list[str]] = {}
    for table_name, group in columns.groupby("table_name", sort=True):
        available = sorted(
            set(group["column_name"].astype(str).str.lower())
        )
        column_summary[str(table_name)] = available

    payload = {
        "status": "pass",
        "tap_url": args.tap_url,
        "table_query_sha256": hashlib.sha256(
            table_query.encode("utf-8")
        ).hexdigest(),
        "column_query_sha256": hashlib.sha256(
            column_query.encode("utf-8")
        ).hexdigest(),
        "candidate_table_count": len(candidates),
        "candidate_tables": [
            {
                "schema_name": str(row.schema_name),
                "table_name": str(row.table_name),
                "description": _text(row.description)[:500],
                "recognized_contract_columns": sorted(
                    required_names
                    & set(column_summary.get(str(row.table_name), []))
                ),
            }
            for row in candidates.itertuples(index=False)
        ],
        "claim_boundary": (
            "This metadata probe returns public table and column names only. "
            "It does not query source rows or establish catalogue overlap."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
