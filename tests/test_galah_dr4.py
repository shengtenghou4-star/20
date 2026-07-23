from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.galah_dr4 import (
    GalahDR4Error,
    build_exact_id_query,
    build_sample_query,
    discover_allspec_table,
    standardize_exact_rows,
    validate_allspec_columns,
)


def test_discover_and_validate_allspec_contract() -> None:
    tables = pd.DataFrame(
        {
            "schema_name": ["galah_dr4", "galah_dr4"],
            "table_name": ["galah_dr4.main_star", "galah_dr4.main_spec"],
        }
    )
    table = discover_allspec_table(tables)
    assert table == "galah_dr4.main_spec"
    columns = pd.DataFrame(
        {
            "column_name": [
                "sobject_id",
                "gaiadr3_source_id",
                "mjd",
                "rv_comp_1",
                "e_rv_comp_1",
                "flag_sp",
                "flag_red",
                "snr_px_ccd3",
            ]
        }
    )
    contract = validate_allspec_columns(columns, table)
    assert contract.table_name == table
    assert "e_rv_comp_1" in contract.available_columns


def test_discovery_rejects_ambiguous_tables() -> None:
    tables = pd.DataFrame(
        {
            "table_name": [
                "galah_dr4.allspec_a",
                "galah_dr4.allspec_b",
            ]
        }
    )
    with pytest.raises(GalahDR4Error, match="expected one"):
        discover_allspec_table(tables)


def test_queries_are_exact_and_bounded() -> None:
    sample = build_sample_query("galah_dr4.main_spec")
    assert "TOP 1" in sample
    assert "e_rv_comp_1 > 0" in sample
    query = build_exact_id_query(
        "galah_dr4.main_spec",
        [2676113965163724160, 1234567890123456789],
    )
    assert "gaiadr3_source_id IN" in query
    assert "2676113965163724160" in query
    with pytest.raises(ValueError, match="at most 50"):
        build_exact_id_query("galah_dr4.main_spec", range(1, 52))


def test_standardize_exact_rows_enforces_identity_and_quality() -> None:
    frame = pd.DataFrame(
        {
            "sobject_id": [1001, 1002, 1003],
            "gaiadr3_source_id": [
                "2676113965163724160",
                "2676113965163724160",
                "999999999999999999",
            ],
            "mjd": [59000.0, 59001.0, 59002.0],
            "rv_comp_1": [12.0, 14.0, 99.0],
            "e_rv_comp_1": [0.2, 0.3, 0.1],
            "flag_sp": [0, 1, 0],
            "flag_red": [0, 0, 0],
            "snr_px_ccd1": [40.0, 40.0, 40.0],
            "snr_px_ccd2": [45.0, 45.0, 45.0],
            "snr_px_ccd3": [50.0, 50.0, 50.0],
            "snr_px_ccd4": [42.0, 42.0, 42.0],
            "rv_comp_nr": [1, 1, 1],
            "rv_comp_1_p": [0.9, 0.9, 0.9],
            "setup": ["single", "single", "single"],
            "survey_name": ["GALAH", "GALAH", "GALAH"],
        }
    )
    rows = standardize_exact_rows(frame, [2676113965163724160])
    assert len(rows) == 2
    assert set(rows["source_id"].astype(int)) == {2676113965163724160}
    assert int(rows["success"].sum()) == 1
    assert rows.loc[rows["obsid"].eq(1002), "rvs_warn"].iloc[0] == 1
    assert rows["source_match_mode"].eq(
        "exact_gaia_dr3_integer_tap_constraint"
    ).all()
