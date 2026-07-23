#!/usr/bin/env python3
"""Freeze the public SDSS DR17 APOGEE star/visit schema.

The probe reads only INFORMATION_SCHEMA column metadata for the three official
SkyServer tables needed to connect a Gaia-labelled APOGEE star to every visit.
No source IDs, coordinates, spectra, velocities, or target rows are queried or
persisted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.skyserver_sql import SkyServerSQLError, skyserver_sql_get

_TABLES = ("apogeeStar", "apogeeStarAllVisit", "apogeeVisit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default=(
            "https://skyserver.sdss.org/dr17/"
            "SkyServerWS/SearchTools/SqlSearch"
        ),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/apogee_dr17_schema_contract.json"),
    )
    return parser.parse_args()


def _column(frame: pd.DataFrame, wanted: str) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    if wanted.lower() not in mapping:
        raise RuntimeError(f"SkyServer metadata is missing {wanted}")
    return mapping[wanted.lower()]


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "release": "SDSS DR17 APOGEE-2",
        "transport": "anonymous_skyserver_sql_csv",
        "row_values_persisted": False,
        "claim_boundary": (
            "This probe freezes public table and column names only. It is not an APOGEE "
            "target overlap, RV, variability, binary, compact-object, or novelty result."
        ),
    }
    try:
        quoted = ",".join(f"'{table}'" for table in _TABLES)
        frame, receipt = skyserver_sql_get(
            args.endpoint,
            (
                "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM "
                "INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME IN "
                f"({quoted}) ORDER BY TABLE_NAME, ORDINAL_POSITION"
            ),
            maximum_rows=2000,
            timeout=args.timeout,
        )
        table_column = _column(frame, "table_name")
        column_column = _column(frame, "column_name")
        type_column = _column(frame, "data_type")
        normalized_table = frame[table_column].astype("string").str.strip()
        discovered: dict[str, list[dict[str, str]]] = {}
        for table in _TABLES:
            rows = frame.loc[normalized_table.str.casefold().eq(table.casefold())]
            if rows.empty:
                raise RuntimeError(f"SkyServer returned no metadata for {table}")
            discovered[table] = [
                {
                    "column_name": str(row[column_column]).strip(),
                    "data_type": str(row[type_column]).strip(),
                }
                for _, row in rows.iterrows()
            ]
        payload.update(
            {
                "status": "pass",
                "tables": discovered,
                "table_column_counts": {
                    table: len(columns) for table, columns in discovered.items()
                },
                "sql_receipt": receipt.to_record(),
            }
        )
    except (SkyServerSQLError, KeyError, TypeError, ValueError, RuntimeError) as error:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:1000]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(args.output.read_text(encoding="utf-8"))
    if payload["status"] != "pass":
        raise RuntimeError(str(payload.get("error", "APOGEE schema probe failed")))


if __name__ == "__main__":
    main()
