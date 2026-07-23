from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_lamost_anonymous_search_submit.py"
_SPEC = importlib.util.spec_from_file_location("probe_lamost_anonymous_search_submit", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

_HTMLContractParser = _MODULE._HTMLContractParser
_csv_contract = _MODULE._csv_contract
_fields = _MODULE._fields


def test_fields_match_live_browser_defaults() -> None:
    row = pd.Series(
        {
            "catalogue_ra": 10.0004738,
            "catalogue_dec": 40.9952444,
        }
    )
    fields = _fields(row)
    assert ("sForm", "0") in fields
    assert ("pos.type", "proximity") in fields
    assert ("output.collection", "typical") in fields
    assert ("output.fmt", "csv") in fields
    assert ("sBtn", "Search") in fields
    mapping = dict(fields)
    assert mapping["output.combined.gaia_source_id"] == "on"
    assert mapping["output.combined.rv"] == "on"
    assert mapping["output.combined.rv_err"] == "on"
    position = mapping["pos.radecTextarea"]
    assert position.startswith("#ra,dec,sep\n")
    assert "10.000473800000,40.995244400000,2.0" in position


def test_csv_contract_accepts_prefixed_columns_and_counts_only() -> None:
    body = (
        b"combined.gaia_source_id,combined.obsid,combined.mjd,combined.rv,"
        b"combined.rv_err,combined.snrg\n"
        b"1234567890123456789,10,59000.1,12.5,1.2,20\n"
        b"2234567890123456789,11,59001.1,,2.0,15\n"
    )
    contract = _csv_contract(body)
    assert contract["missing_required_columns"] == []
    assert contract["result_row_count"] == 2
    assert contract["exact_digit_identity_rows"] == 2
    assert contract["finite_rv_rows"] == 1
    assert contract["finite_positive_rv_error_rows"] == 2
    assert contract["finite_rv_with_positive_error_rows"] == 1
    assert "1234567890123456789" not in str(contract)
    assert "12.5" not in str(contract)


def test_csv_contract_reports_missing_columns_without_values() -> None:
    contract = _csv_contract(b"obsid,mjd\n10,59000\n")
    assert contract["result_row_count"] == 1
    assert set(contract["missing_required_columns"]) == {
        "gaia_source_id",
        "rv",
        "rv_err",
    }
    assert "59000" not in str(contract)


def test_html_contract_records_paths_without_query_tokens() -> None:
    parser = _HTMLContractParser("https://www.lamost.org/dr8/v2.0/result?id=secret")
    parser.feed(
        "<html><table><tr><th>RV</th><th>RV error</th></tr></table>"
        "<a href='/dr8/v2.0/download?query_id=secret-7'>Download</a></html>"
    )
    assert parser.headers == ["RV", "RV error"]
    assert parser.paths == {"/dr8/v2.0/download"}
    assert "secret-7" not in str(parser.paths)
