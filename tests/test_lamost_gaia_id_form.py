from __future__ import annotations

from hou_compact.lamost_gaia_id_form import (
    build_gaia_id_form_fields,
    normalize_source_ids,
    standardize_gaia_id_response,
)
from hou_compact.lamost_search_form import SearchFormReceipt
import pytest


def _receipt() -> SearchFormReceipt:
    return SearchFormReceipt(
        endpoint="https://example.test/q",
        final_path="/q",
        status=200,
        attempts=1,
        request_bytes=100,
        request_sha256="a" * 64,
        response_bytes=200,
        response_sha256="b" * 64,
        content_type="",
        response_kind="binary",
    )


def test_build_gaia_id_fields_uses_native_constraint_without_coordinates() -> None:
    ids = [2676113965163724160, 1234567890123456789]
    fields = build_gaia_id_form_fields(ids)
    mapping = dict(fields)
    assert mapping["pos.type"] == "none"
    assert mapping["gaiasourcearea"].splitlines() == [
        "#gaia_source_id",
        "2676113965163724160",
        "1234567890123456789",
    ]
    assert "pos.radecTextarea" not in mapping
    assert mapping["output.combined.rv"] == "on"
    assert mapping["output.combined.rv_err"] == "on"


def test_normalize_source_ids_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="unique"):
        normalize_source_ids([2676113965163724160, 2676113965163724160])


def test_standardize_gaia_id_response_retains_exact_ids_and_marks_missing_rv_bad() -> None:
    body = (
        b"combined_gaia_source_id|combined_obsid|combined_mjd|combined_rv|"
        b"combined_rv_err|combined_snrg|combined_snri|combined_snrz|"
        b"combined_fibermask|combined_class|combined_subclass\n"
        b"2676113965163724160|1001|59000.5|12.3|0.8|30|31|29|0|STAR|G5\n"
        b"2676113965163724160|1002|59001.5|||20|21|19|0|STAR|G5\n"
        b"999999999999999999|1003|59002.5|15.0|1.2|20|21|19|0|STAR|K0\n"
    )
    epochs, receipt = standardize_gaia_id_response(
        body,
        [2676113965163724160],
        _receipt(),
    )
    assert len(epochs) == 2
    assert set(epochs["source_id"].astype(int)) == {2676113965163724160}
    assert int(epochs["success"].sum()) == 1
    missing_row = epochs.loc[epochs["obsid"].eq(1002)].iloc[0]
    assert not bool(missing_row["success"])
    assert int(missing_row["rvs_warn"]) == 1
    assert epochs.iloc[0]["source_match_mode"] == (
        "exact_gaia_dr3_character_id_direct_form_constraint"
    )
    record = receipt.to_record()
    assert record["input_target_count"] == 1
    assert record["returned_row_count"] == 3
    assert record["exact_identity_row_count"] == 2
