from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.lamost_tap_mec import (
    LamostTapMecError,
    MecTableSpec,
    build_exact_mec_query,
    candidate_safe_mec_summary,
    discover_mec_table_specs,
    query_exact_mec_rows,
)


class _Service:
    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self.frames = list(frames)
        self.queries: list[str] = []

    def run_sync(self, query: str, *, maxrec: int) -> pd.DataFrame:
        assert maxrec > 0
        self.queries.append(query)
        return self.frames.pop(0)


def _schema_frame(datatype: str) -> pd.DataFrame:
    columns = [
        "source_id",
        "gaia_source_id",
        "obs_number",
        "obsid_list",
        "midmjm_list",
        "rv_list",
    ]
    return pd.DataFrame(
        {
            "table_name": ["dr8.lrs_multiple_epoch"] * len(columns),
            "column_name": columns,
            "datatype": [datatype if name == "gaia_source_id" else "VARCHAR" for name in columns],
        }
    )


def test_discovery_accepts_integer_identity_and_rejects_float_identity() -> None:
    integer_service = _Service([_schema_frame("BIGINT")])
    specs = discover_mec_table_specs(integer_service)
    assert len(specs) == 1
    assert specs[0].identity_literal_mode == "integer"

    float_service = _Service([_schema_frame("DOUBLE")])
    with pytest.raises(LamostTapMecError, match="preserves Gaia identifiers"):
        discover_mec_table_specs(float_service)


def test_text_identity_query_quotes_only_normalized_integer_literals() -> None:
    spec = MecTableSpec(
        table_name="dr8.lrs_multiple_epoch",
        source_id_column="source_id",
        gaia_source_id_column="gaia_source_id",
        obs_number_column="obs_number",
        obsid_list_column="obsid_list",
        midmjm_list_column="midmjm_list",
        rv_list_column="rv_list",
        gaia_source_id_datatype="VARCHAR",
        identity_literal_mode="text",
        priority=0,
    )
    query = build_exact_mec_query(spec, [10, 20])
    assert "IN ('10', '20')" in query
    assert ";" not in query


def test_exact_query_retains_unique_and_ambiguous_statuses() -> None:
    spec = MecTableSpec(
        table_name="dr8.lrs_multiple_epoch",
        source_id_column="source_id",
        gaia_source_id_column="gaia_source_id",
        obs_number_column="obs_number",
        obsid_list_column="obsid_list",
        midmjm_list_column="midmjm_list",
        rv_list_column="rv_list",
        gaia_source_id_datatype="BIGINT",
        identity_literal_mode="integer",
        priority=0,
    )
    frame = pd.DataFrame(
        {
            "source_id": ["A", "B", "C"],
            "gaia_source_id": [10, 20, 20],
            "obs_number": [2, 2, 2],
            "obsid_list": ["1-2", "3-4", "5-6"],
            "midmjm_list": ["100-200", "300-400", "500-600"],
            "rv_list": ["1.0-2.0", "3.0-4.0", "5.0-6.0"],
        }
    )
    service = _Service([frame])
    rows, receipts = query_exact_mec_rows(
        service,
        spec,
        [10, 20, 30],
        batch_size=3,
        maxrec_per_batch=10,
    )
    status_by_id = rows.groupby("gaia_source_id")["tap_mec_status"].first().to_dict()
    assert status_by_id == {10: "accepted_unique", 20: "ambiguous_multiple_rows"}
    summary = candidate_safe_mec_summary(3, rows, [spec], receipts)
    assert summary["accepted_unique_gaia_dr2_count"] == 1
    assert summary["matched_gaia_dr2_count"] == 2
    assert summary["unmatched_gaia_dr2_count"] == 1
    assert "10" not in str(summary)


def test_exact_query_rejects_rows_outside_requested_identity_set() -> None:
    spec = MecTableSpec(
        table_name="dr8.lrs_multiple_epoch",
        source_id_column="source_id",
        gaia_source_id_column="gaia_source_id",
        obs_number_column="obs_number",
        obsid_list_column="obsid_list",
        midmjm_list_column="midmjm_list",
        rv_list_column="rv_list",
        gaia_source_id_datatype="BIGINT",
        identity_literal_mode="integer",
        priority=0,
    )
    frame = pd.DataFrame(
        {
            "source_id": ["A"],
            "gaia_source_id": [999],
            "obs_number": [2],
            "obsid_list": ["1-2"],
            "midmjm_list": ["100-200"],
            "rv_list": ["1.0-2.0"],
        }
    )
    with pytest.raises(LamostTapMecError, match="outside the exact query"):
        query_exact_mec_rows(
            _Service([frame]),
            spec,
            [10],
            batch_size=1,
            maxrec_per_batch=5,
        )
