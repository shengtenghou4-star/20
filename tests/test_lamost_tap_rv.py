from __future__ import annotations

import re

import pandas as pd
import pytest

from hou_compact.lamost_tap_rv import (
    RvTableSpec,
    build_exact_obsid_query,
    candidate_safe_tap_summary,
    discover_rv_table_specs,
    normalize_obsids,
    query_exact_obsids,
)


class _Result:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def to_table(self) -> pd.DataFrame:
        return self._frame


class _FakeService:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def run_sync(self, query: str, maxrec: int) -> _Result:
        self.queries.append(query)
        if "TAP_SCHEMA.columns" in query:
            return _Result(
                pd.DataFrame(
                    {
                        "table_name": [
                            "dr8.lrs_afgk",
                            "dr8.lrs_afgk",
                            "dr8.lrs_afgk",
                            "dr8.lrs_afgk",
                            "dr8.lrs_mstar",
                            "dr8.lrs_mstar",
                            "dr8.lrs_mstar",
                            "dr8.general",
                        ],
                        "column_name": [
                            "obsid",
                            "rv",
                            "rv_err",
                            "snrg",
                            "obsid",
                            "rv",
                            "rv_err",
                            "obsid",
                        ],
                    }
                )
            )
        obsids = [int(value) for value in re.findall(r"\b\d+\b", query.split("IN", 1)[1])]
        if "dr8.lrs_afgk" in query:
            records = [
                {"obsid": value, "rv": float(value), "rv_err": 1.0, "snrg": 20.0}
                for value in obsids
                if value in {101, 202}
            ]
            return _Result(pd.DataFrame.from_records(records))
        if "dr8.lrs_mstar" in query:
            records = []
            if 202 in obsids:
                records.append({"obsid": 202, "rv": 999.0, "rv_err": 2.0})
            if 303 in obsids:
                records.append({"obsid": 303, "rv": -30.0, "rv_err": -1.0})
            return _Result(pd.DataFrame.from_records(records))
        raise AssertionError(f"unexpected query: {query}")


def test_discover_rv_tables_requires_all_three_core_columns() -> None:
    service = _FakeService()
    specs = discover_rv_table_specs(service)
    assert [spec.table_name for spec in specs] == ["dr8.lrs_afgk", "dr8.lrs_mstar"]
    assert specs[0].priority < specs[1].priority
    assert "dr8.general" not in [spec.table_name for spec in specs]


def test_exact_query_uses_only_integer_literals() -> None:
    spec = RvTableSpec("dr8.lrs_afgk", ("obsid", "rv", "rv_err"), 0)
    query = build_exact_obsid_query(spec, [101, 202])
    assert query == (
        "SELECT obsid, rv, rv_err FROM dr8.lrs_afgk "
        "WHERE obsid IN (101, 202)"
    )
    with pytest.raises(ValueError):
        build_exact_obsid_query(spec, [202, 101])


def test_query_exact_obsids_prefers_high_priority_valid_row() -> None:
    service = _FakeService()
    specs = discover_rv_table_specs(service)
    rows, receipts = query_exact_obsids(
        service,
        specs,
        [303, 202, 101, 202],
        batch_size=2,
        maxrec_per_batch=4,
    )
    assert rows["obsid"].tolist() == [101, 202, 303]
    chosen_202 = rows.loc[rows["obsid"].eq(202)].iloc[0]
    assert chosen_202["tap_table"] == "dr8.lrs_afgk"
    assert chosen_202["rv"] == 202.0
    assert chosen_202["matched_table_count"] == 2
    chosen_303 = rows.loc[rows["obsid"].eq(303)].iloc[0]
    assert chosen_303["tap_rv_status"] == "invalid_or_missing_uncertainty"
    assert len(receipts) == 4

    summary = candidate_safe_tap_summary(3, rows, specs, receipts)
    assert summary["matched_obsid_count"] == 3
    assert summary["scorable_obsid_count"] == 2
    assert summary["obsids_seen_in_multiple_tables"] == 1
    assert "101" not in str(summary)


def test_obsid_normalization_rejects_lossy_or_unsafe_text() -> None:
    assert normalize_obsids(["2", 1, "2"]) == [1, 2]
    for value in ("1.0", "1e3", "-1", "1 OR 1=1", ""):
        with pytest.raises(ValueError):
            normalize_obsids([value])
