#!/usr/bin/env python3
"""Compatibility probe for LAMOST form CSVs with ``combined_`` headers."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import probe_lamost_obsid_csv as base  # noqa: E402

_COMBINED_PREFIX = "combined_"
_ORIGINAL_PARSE = base._parse_delimited


def _normalize_parsed(parsed):
    if parsed is None:
        return None
    delimiter, columns, row_count, rows = parsed
    normalized = [
        column[len(_COMBINED_PREFIX) :]
        if column.startswith(_COMBINED_PREFIX)
        else column
        for column in columns
    ]
    if any(not column for column in normalized):
        raise base.ObsidCsvProbeError("normalized LAMOST column name is empty")
    if len(set(normalized)) != len(normalized):
        raise base.ObsidCsvProbeError(
            "LAMOST combined-column normalization created duplicate headers"
        )
    return delimiter, normalized, row_count, rows


def _parse_delimited_compat(raw: bytes):
    return _normalize_parsed(_ORIGINAL_PARSE(raw))


def main() -> None:
    base._parse_delimited = _parse_delimited_compat
    base.main()


if __name__ == "__main__":
    main()
