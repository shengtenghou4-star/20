from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.lamost_dr3_spectra import (
    DR3SpectrumSpec,
    LamostDR3SpectrumError,
    build_contract_probe_query,
    build_exact_dr3_spectrum_query,
    candidate_safe_dr3_spectrum_summary,
    query_exact_dr3_spectra,
)


class _Service:
    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self.frames = iter(frames)
        self.queries: list[tuple[str, int]] = []

    def run_sync(self, query: str, *, maxrec: int) -> pd.DataFrame:
        self.queries.append((query, maxrec))
        return next(self.frames)


def _row(source_id: str = "1234567890123456789", obsid: int = 10) -> dict[str, object]:
    return {
        "gaia_source_id": source_id,
        "obsid": obsid,
        "mjd": "59000.125",
        "rv": 32.5,
        "rv_err": 1.2,
        "snrg": 20.0,
        "snri": 30.0,
        "snrz": 15.0,
        "fibermask": 0,
        "class": "STAR",
        "subclass": "G5",
    }


def test_exact_query_quotes_gaia_dr3_character_ids() -> None:
    spec = DR3SpectrumSpec()
    query = build_exact_dr3_spectrum_query(
        spec,
        [1234567890123456789, 2234567890123456789],
    )
    assert "FROM stellar" in query
    assert "gaia_source_id IN ('1234567890123456789', '2234567890123456789')" in query
    assert "rv_err" in query
    assert "mjd" in query


def test_contract_probe_contains_no_source_identifier_values() -> None:
    query = build_contract_probe_query()
    assert "FROM stellar" in query
    assert "WHERE 1 = 0" in query
    assert "123456" not in query


def test_query_standardizes_direct_dr3_rows() -> None:
    service = _Service([pd.DataFrame([_row()])])
    rows, receipts = query_exact_dr3_spectra(
        service,
        ["1234567890123456789"],
        batch_size=1,
        maxrec_per_batch=5,
    )
    assert len(rows) == 1
    row = rows.iloc[0]
    assert int(row["source_id"]) == 1234567890123456789
    assert int(row["obsid"]) == 10
    assert row["mjd"] == pytest.approx(59000.125)
    assert row["vrad"] == pytest.approx(32.5)
    assert row["vrad_err"] == pytest.approx(1.2)
    assert bool(row["success"])
    assert int(row["rvs_warn"]) == 0
    assert int(row["fiberstatus"]) == 0
    assert row["source_match_mode"] == "exact_gaia_dr3_character_id"
    assert len(receipts) == 1
    assert "1234567890123456789" not in str(receipts[0].to_record())


def test_bad_fibermask_fails_closed_without_dropping_provenance() -> None:
    raw = _row()
    raw["fibermask"] = 4
    service = _Service([pd.DataFrame([raw])])
    rows, _ = query_exact_dr3_spectra(service, [raw["gaia_source_id"]])
    assert len(rows) == 1
    assert not bool(rows.iloc[0]["success"])
    assert int(rows.iloc[0]["rvs_warn"]) == 1
    assert int(rows.iloc[0]["fiberstatus"]) == 4


def test_query_rejects_ids_outside_exact_batch() -> None:
    service = _Service([pd.DataFrame([_row(source_id="2234567890123456789")])])
    with pytest.raises(LamostDR3SpectrumError, match="outside"):
        query_exact_dr3_spectra(service, ["1234567890123456789"])


def test_query_rejects_duplicate_obsids() -> None:
    service = _Service(
        [pd.DataFrame([_row(obsid=10), _row(obsid=10)])]
    )
    with pytest.raises(LamostDR3SpectrumError, match="duplicate obsid"):
        query_exact_dr3_spectra(service, ["1234567890123456789"])


def test_zero_match_is_valid_and_summary_is_identifier_safe() -> None:
    service = _Service([pd.DataFrame(columns=list(_row().keys()))])
    rows, receipts = query_exact_dr3_spectra(
        service,
        ["1234567890123456789"],
    )
    summary = candidate_safe_dr3_spectrum_summary(1, rows, receipts)
    assert summary["matched_gaia_dr3_count"] == 0
    assert summary["unmatched_gaia_dr3_count"] == 1
    assert summary["spectrum_rows"] == 0
    assert "1234567890123456789" not in str(summary)
