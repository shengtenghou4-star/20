from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.lamost_form_rv import (
    FormRVConfig,
    LamostFormRVError,
    build_browser_form_fields,
    candidate_safe_form_rv_summary,
    parse_browser_csv,
    query_candidate_batches,
)
from hou_compact.lamost_search_form import SearchFormReceipt


def _receipt(seed: int = 1) -> SearchFormReceipt:
    return SearchFormReceipt(
        endpoint="https://www.lamost.org/dr8/v2.0/q",
        final_path="/dr8/v2.0/q",
        status=200,
        attempts=1,
        request_bytes=100 + seed,
        request_sha256=f"{'a' * 63}{seed % 10}",
        response_bytes=200 + seed,
        response_sha256=f"{'b' * 63}{seed % 10}",
        content_type="text/csv",
        response_kind="csv",
    )


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": ["1234567890123456789", "2234567890123456789"],
            "ra": [10.0, 20.0],
            "dec": [30.0, -40.0],
        }
    )


def test_browser_fields_use_positions_only_for_discovery() -> None:
    fields = build_browser_form_fields(_candidates(), separation_arcsec=2.0)
    mapping = dict(fields)
    assert mapping["sForm"] == "0"
    assert mapping["pos.type"] == "proximity"
    assert mapping["output.fmt"] == "csv"
    assert mapping["output.combined.gaia_source_id"] == "on"
    assert mapping["output.combined.rv"] == "on"
    assert mapping["output.combined.rv_err"] == "on"
    positions = mapping["pos.radecTextarea"]
    assert positions.splitlines()[0] == "#ra,dec,sep"
    assert "10.000000000000,30.000000000000,2" in positions
    assert "1234567890123456789" not in positions


def test_parse_browser_csv_normalizes_documented_fields() -> None:
    raw = parse_browser_csv(
        b"combined.gaia_source_id,combined.obsid,combined.mjd,combined.rv,"
        b"combined.rv_err,combined.snrg,combined.snri,combined.snrz,"
        b"combined.fibermask,combined.class,combined.subclass\n"
        b"1234567890123456789,10,59000.1,12.5,1.2,20,30,15,0,STAR,G5\n"
    )
    assert list(raw.columns) == [
        "gaia_source_id",
        "obsid",
        "mjd",
        "rv",
        "rv_err",
        "snrg",
        "snri",
        "snrz",
        "fibermask",
        "class",
        "subclass",
    ]
    assert raw.iloc[0]["gaia_source_id"] == "1234567890123456789"


def test_query_batches_rejects_neighbours_by_exact_identity() -> None:
    csv = (
        b"gaia_source_id,obsid,mjd,rv,rv_err,snrg,snri,snrz,fibermask,class,subclass\n"
        b"1234567890123456789,10,59000.1,12.5,1.2,20,30,15,0,STAR,G5\n"
        b"9994567890123456789,11,59001.1,80.0,2.0,10,12,8,0,STAR,K0\n"
    )

    def submitter(fields: list[tuple[str, object]]) -> tuple[bytes, SearchFormReceipt]:
        assert dict(fields)["pos.type"] == "proximity"
        return csv, _receipt()

    rows, receipts = query_candidate_batches(
        _candidates(),
        submitter,
        config=FormRVConfig(batch_size=2),
    )
    assert len(rows) == 1
    assert int(rows.iloc[0]["source_id"]) == 1234567890123456789
    assert bool(rows.iloc[0]["success"])
    assert rows.iloc[0]["source_match_mode"] == (
        "exact_gaia_dr3_character_id_after_positional_discovery"
    )
    assert receipts[0].returned_row_count == 2
    assert receipts[0].exact_identity_row_count == 1


def test_bad_fibermask_is_retained_but_fails_quality() -> None:
    csv = (
        b"gaia_source_id,obsid,mjd,rv,rv_err,snrg,snri,snrz,fibermask,class,subclass\n"
        b"1234567890123456789,10,59000.1,12.5,1.2,20,30,15,4,STAR,G5\n"
    )

    def submitter(_: list[tuple[str, object]]) -> tuple[bytes, SearchFormReceipt]:
        return csv, _receipt()

    rows, _ = query_candidate_batches(
        _candidates().iloc[:1],
        submitter,
    )
    assert len(rows) == 1
    assert not bool(rows.iloc[0]["success"])
    assert int(rows.iloc[0]["rvs_warn"]) == 1
    assert int(rows.iloc[0]["fiberstatus"]) == 4


def test_duplicate_obsid_across_batches_is_rejected() -> None:
    candidates = _candidates()
    responses = iter(
        [
            (
                b"gaia_source_id,obsid,mjd,rv,rv_err,snrg,snri,snrz,fibermask,class,subclass\n"
                b"1234567890123456789,10,59000,1,1,10,10,10,0,STAR,G\n"
            ),
            (
                b"gaia_source_id,obsid,mjd,rv,rv_err,snrg,snri,snrz,fibermask,class,subclass\n"
                b"2234567890123456789,10,59001,2,1,10,10,10,0,STAR,G\n"
            ),
        ]
    )

    def submitter(_: list[tuple[str, object]]) -> tuple[bytes, SearchFormReceipt]:
        return next(responses), _receipt()

    with pytest.raises(LamostFormRVError, match="multiple positional batches"):
        query_candidate_batches(
            candidates,
            submitter,
            config=FormRVConfig(batch_size=1),
        )


def test_candidate_safe_summary_contains_no_identifiers_or_velocities() -> None:
    csv = (
        b"gaia_source_id,obsid,mjd,rv,rv_err,snrg,snri,snrz,fibermask,class,subclass\n"
        b"1234567890123456789,10,59000.1,12.5,1.2,20,30,15,0,STAR,G5\n"
    )

    def submitter(_: list[tuple[str, object]]) -> tuple[bytes, SearchFormReceipt]:
        return csv, _receipt()

    rows, receipts = query_candidate_batches(
        _candidates().iloc[:1],
        submitter,
    )
    summary = candidate_safe_form_rv_summary(
        1,
        rows,
        receipts,
        FormRVConfig(),
    )
    serialized = str(summary)
    assert summary["matched_source_count"] == 1
    assert summary["quality_pass_epoch_rows"] == 1
    assert "1234567890123456789" not in serialized
    assert "59000.1" not in serialized
    assert "12.5" not in serialized
