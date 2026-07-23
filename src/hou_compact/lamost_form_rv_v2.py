"""Compatibility layer for current LAMOST DR8 form response headers.

The public form currently prefixes selected output columns with ``combined_``.
This module normalizes that transport-specific prefix before invoking the strict
exact-obsid validation in :mod:`hou_compact.lamost_form_rv`.
"""

from __future__ import annotations

from typing import Any

from hou_compact import lamost_form_rv as base

_COMBINED_PREFIX = "combined_"
_BASE_PARSE = base._parse_delimited


def normalize_parsed_table(table: base.ParsedTable | None) -> base.ParsedTable | None:
    if table is None:
        return None
    columns = tuple(
        column[len(_COMBINED_PREFIX) :]
        if column.startswith(_COMBINED_PREFIX)
        else column
        for column in table.columns
    )
    if any(not column for column in columns):
        raise base.LamostFormError("normalized LAMOST column name is empty")
    if len(set(columns)) != len(columns):
        raise base.LamostFormError(
            "LAMOST combined-column normalization created duplicate headers"
        )
    return base.ParsedTable(
        delimiter=table.delimiter,
        columns=columns,
        rows=table.rows,
        response_sha256=table.response_sha256,
        response_bytes=table.response_bytes,
        source_kind=table.source_kind,
        source_url_path=table.source_url_path,
    )


def _parse_delimited_compat(
    raw: bytes,
    *,
    source_kind: str,
    source_url: str,
) -> base.ParsedTable | None:
    return normalize_parsed_table(
        _BASE_PARSE(raw, source_kind=source_kind, source_url=source_url)
    )


def acquire_form_rv(**kwargs: Any) -> dict[str, object]:
    """Run the frozen client with current first-party header normalization."""

    previous = base._parse_delimited
    base._parse_delimited = _parse_delimited_compat
    try:
        return base.acquire_form_rv(**kwargs)
    finally:
        base._parse_delimited = previous
