"""Candidate-safe discovery of the official LAMOST IVOA TAP schema."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import pandas as pd
import pyvo

from hou_compact.lamost_openapi import REQUIRED_MULTIEPOCH_COLUMNS


class LAMOSTTapError(RuntimeError):
    """Raised when the official TAP metadata cannot prove the frozen contract."""


def _query_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def execute_tap_get(tap_url: str, sql: str, maxrec: int) -> pd.DataFrame:
    """Execute a synchronous TAP query with GET.

    The LAMOST DR8 TAP service currently rejects POST requests to ``/sync`` with
    HTTP 405. PyVO exposes the standards-compliant GET path through
    ``TAPQuery.execute_votable(post=False)``.
    """

    query = pyvo.dal.TAPQuery(
        tap_url,
        sql,
        mode="sync",
        language="ADQL",
        maxrec=maxrec,
    )
    votable = query.execute_votable(post=False)
    table = votable.get_first_table()
    if table is None:
        raise LAMOSTTapError("TAP response contains no result table")
    frame = table.to_table(use_names_over_ids=True).to_pandas()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    return frame


def discover_lamost_tap_contract(
    tap_url: str,
    *,
    maximum_tables: int = 10_000,
    maximum_columns: int = 100_000,
    query_executor: Callable[[str, str, int], pd.DataFrame] = execute_tap_get,
) -> dict[str, object]:
    """Discover a DR8 LRS multiple-epoch table from public TAP_SCHEMA metadata.

    The function reads schema metadata only. It requires the complete frozen set of
    multiple-epoch columns in one table and fails closed if the metadata query reaches
    either configured row ceiling.
    """

    if not tap_url.startswith("https://"):
        raise ValueError("tap_url must use HTTPS")
    if maximum_tables < 1 or maximum_columns < 1:
        raise ValueError("metadata row ceilings must be positive")

    table_sql = (
        "SELECT TOP {maximum} schema_name, table_name, description "
        "FROM TAP_SCHEMA.tables ORDER BY schema_name, table_name"
    ).format(maximum=maximum_tables)
    column_sql = (
        "SELECT TOP {maximum} table_name, column_name, datatype, description "
        "FROM TAP_SCHEMA.columns ORDER BY table_name, column_name"
    ).format(maximum=maximum_columns)

    tables = query_executor(tap_url, table_sql, maximum_tables + 1).copy()
    columns = query_executor(tap_url, column_sql, maximum_columns + 1).copy()
    tables.columns = [str(column).strip().lower() for column in tables.columns]
    columns.columns = [str(column).strip().lower() for column in columns.columns]
    required_table_fields = {"schema_name", "table_name", "description"}
    required_column_fields = {"table_name", "column_name", "datatype", "description"}
    missing_table_fields = sorted(required_table_fields - set(tables.columns))
    missing_column_fields = sorted(required_column_fields - set(columns.columns))
    if missing_table_fields:
        raise LAMOSTTapError(
            f"TAP_SCHEMA.tables is missing columns: {missing_table_fields}"
        )
    if missing_column_fields:
        raise LAMOSTTapError(
            f"TAP_SCHEMA.columns is missing columns: {missing_column_fields}"
        )
    if len(tables) >= maximum_tables:
        raise LAMOSTTapError(
            "TAP table discovery reached maximum_tables and may be truncated"
        )
    if len(columns) >= maximum_columns:
        raise LAMOSTTapError(
            "TAP column discovery reached maximum_columns and may be truncated"
        )

    for name in ("schema_name", "table_name", "description"):
        tables[name] = tables[name].map(_text)
    for name in ("table_name", "column_name", "datatype", "description"):
        columns[name] = columns[name].map(_text)
    columns["column_name_normalized"] = columns["column_name"].str.strip().str.lower()

    required = set(REQUIRED_MULTIEPOCH_COLUMNS)
    candidates: list[dict[str, object]] = []
    for table_name, group in columns.groupby("table_name", sort=True):
        available = set(group["column_name_normalized"])
        if not required.issubset(available):
            continue
        table_rows = tables.loc[
            tables["table_name"].eq(str(table_name))
            | (tables["schema_name"] + "." + tables["table_name"]).eq(str(table_name))
        ]
        descriptions = sorted(
            {
                value
                for value in table_rows["description"].map(_text)
                if value
            }
        )
        schema_names = sorted(
            {
                value
                for value in table_rows["schema_name"].map(_text)
                if value
            }
        )
        public_columns = [
            {
                "column_name": str(row.column_name),
                "datatype": str(row.datatype),
                "description": str(row.description)[:500],
            }
            for row in group.sort_values(
                "column_name_normalized",
                kind="stable",
            ).itertuples(index=False)
        ]
        candidates.append(
            {
                "table_name": str(table_name),
                "schema_names": schema_names,
                "descriptions": descriptions,
                "matched_required_columns": sorted(required),
                "column_count": len(group),
                "columns": public_columns,
            }
        )

    if not candidates:
        likely = []
        for table_name, group in columns.groupby("table_name", sort=True):
            available = set(group["column_name_normalized"])
            hits = sorted(required & available)
            haystack = f"{table_name} " + " ".join(available)
            name_signal = any(
                token in haystack.lower()
                for token in ("multiple", "epoch", "repeat", "multi_epoch")
            )
            if hits or name_signal:
                likely.append(
                    {
                        "table_name": str(table_name),
                        "matched_required_columns": hits,
                        "missing_required_columns": sorted(required - available),
                    }
                )
        raise LAMOSTTapError(
            "no TAP table contains the frozen LAMOST multiple-epoch column set; "
            f"near_matches={likely[:20]}"
        )

    return {
        "status": "pass",
        "tap_url": tap_url,
        "transport": "sync_get",
        "table_query_sha256": _query_hash(table_sql),
        "column_query_sha256": _query_hash(column_sql),
        "tap_table_count": len(tables),
        "tap_column_count": len(columns),
        "required_columns": sorted(required),
        "candidate_table_count": len(candidates),
        "candidate_tables": candidates,
        "claim_boundary": (
            "This result contains public TAP schema metadata only. It queries no "
            "catalogue rows and establishes no source overlap or orbit result."
        ),
    }
