from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.lamost_openapi import REQUIRED_MULTIEPOCH_COLUMNS
from hou_compact.lamost_tap import LAMOSTTapError, discover_lamost_tap_contract


def _query_executor(include_all: bool = True):
    tables = pd.DataFrame(
        [
            {
                "schema_name": "dr8_v1",
                "table_name": "lrs_multiple_epoch",
                "description": "LAMOST LRS Multiple Epoch Catalog",
            }
        ]
    )
    names = list(REQUIRED_MULTIEPOCH_COLUMNS)
    if not include_all:
        names.remove("rv_list")
    names.extend(["source_id", "gaia_g_mean_mag"])
    columns = pd.DataFrame(
        [
            {
                "table_name": "lrs_multiple_epoch",
                "column_name": name,
                "datatype": "VARCHAR" if name.endswith("_list") else "BIGINT",
                "description": name,
            }
            for name in names
        ]
    )

    def execute(tap_url: str, sql: str, maxrec: int) -> pd.DataFrame:
        assert tap_url == "https://example.org/tap"
        assert maxrec > 0
        if "TAP_SCHEMA.tables" in sql:
            return tables.copy()
        if "TAP_SCHEMA.columns" in sql:
            return columns.copy()
        raise AssertionError(sql)

    return execute


def test_discovers_complete_multiple_epoch_contract() -> None:
    result = discover_lamost_tap_contract(
        "https://example.org/tap",
        query_executor=_query_executor(),
    )
    assert result["transport"] == "sync_get"
    assert result["candidate_table_count"] == 1
    candidate = result["candidate_tables"][0]
    assert candidate["table_name"] == "lrs_multiple_epoch"
    assert candidate["matched_required_columns"] == sorted(REQUIRED_MULTIEPOCH_COLUMNS)


def test_fails_closed_on_incomplete_contract() -> None:
    with pytest.raises(LAMOSTTapError, match="no TAP table"):
        discover_lamost_tap_contract(
            "https://example.org/tap",
            query_executor=_query_executor(include_all=False),
        )


def test_requires_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        discover_lamost_tap_contract(
            "http://example.org/tap",
            query_executor=_query_executor(),
        )
