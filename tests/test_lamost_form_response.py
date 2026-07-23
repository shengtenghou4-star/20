from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.lamost_form_response import (
    LamostFormResponseError,
    detect_delimiter,
    parse_delimited_response,
    resolve_column,
)


def test_detects_live_pipe_delimiter() -> None:
    body = b"combined_obsid|combined_mjd|combined_rv_err|combined_rv\n10|59000|1.2|12.5\n"
    assert detect_delimiter(body) == "|"
    frame = parse_delimited_response(body)
    assert list(frame.columns) == [
        "combined_obsid",
        "combined_mjd",
        "combined_rv_err",
        "combined_rv",
    ]
    assert frame.iloc[0]["combined_rv"] == "12.5"
    assert resolve_column(frame, "rv") == "combined_rv"
    assert resolve_column(frame, "rv_err") == "combined_rv_err"


def test_parses_comma_and_drops_trailing_empty_column() -> None:
    frame = parse_delimited_response(
        b"gaia_source_id,obsid,rv,rv_err,\n1234567890123456789,10,2.5,0.4,\n"
    )
    assert list(frame.columns) == ["gaia_source_id", "obsid", "rv", "rv_err"]
    assert resolve_column(frame, "gaia_source_id") == "gaia_source_id"


def test_parses_tab_delimiter() -> None:
    frame = parse_delimited_response(b"obsid\tmjd\trv\trv_err\n10\t59000\t2.5\t0.4\n")
    expected = pd.DataFrame(
        {"obsid": ["10"], "mjd": ["59000"], "rv": ["2.5"], "rv_err": ["0.4"]},
        dtype="string",
    )
    pd.testing.assert_frame_equal(frame, expected)


def test_rejects_plain_error_text() -> None:
    with pytest.raises(LamostFormResponseError, match="delimiter"):
        parse_delimited_response(b"query failed")
