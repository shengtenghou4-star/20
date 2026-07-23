from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.desi_dr1 import (
    DesiDR1Error,
    build_exact_id_query,
    build_sample_query,
    single_epoch_rvtab_url,
    standardize_coadd_rows,
    validate_mws_columns,
)


def test_validate_mws_columns_and_queries() -> None:
    columns = pd.DataFrame(
        {
            "column_name": [
                "source_id",
                "targetid",
                "healpix",
                "survey",
                "program",
                "srcfile",
                "vrad",
                "vrad_err",
                "rvs_warn",
                "success",
                "sn_b",
                "sn_r",
                "sn_z",
            ]
        }
    )
    contract = validate_mws_columns(columns)
    assert contract.table_name == "desi_dr1.mws"
    assert "targetid" in contract.available_columns
    sample = build_sample_query()
    assert "program <> 'backup'" in sample
    exact = build_exact_id_query(
        [2676113965163724160, 1234567890123456789]
    )
    assert "source_id IN" in exact
    assert "2676113965163724160" in exact
    with pytest.raises(ValueError, match="at most 50"):
        build_exact_id_query(range(1, 52))


def test_validate_mws_columns_rejects_missing_locator() -> None:
    columns = pd.DataFrame({"column_name": ["source_id", "targetid"]})
    with pytest.raises(DesiDR1Error, match="healpix"):
        validate_mws_columns(columns)


def test_standardize_coadd_rows_enforces_identity_and_excludes_backup() -> None:
    frame = pd.DataFrame(
        {
            "source_id": [
                "2676113965163724160",
                "2676113965163724160",
                "999999999999999999",
            ],
            "targetid": [1001, 1002, 1003],
            "healpix": [2152, 2153, 2154],
            "survey": ["main", "main", "main"],
            "program": ["bright", "backup", "dark"],
            "srcfile": ["a", "b", "c"],
            "vrad": [12.0, 14.0, 99.0],
            "vrad_err": [0.2, 0.3, 0.1],
            "rvs_warn": [0, 0, 0],
            "success": [1, 1, 1],
            "sn_b": [10.0, 10.0, 10.0],
            "sn_r": [20.0, 20.0, 20.0],
            "sn_z": [15.0, 15.0, 15.0],
        }
    )
    rows = standardize_coadd_rows(frame, [2676113965163724160])
    assert len(rows) == 1
    assert int(rows.iloc[0]["source_id"]) == 2676113965163724160
    assert rows.iloc[0]["program"] == "bright"
    assert bool(rows.iloc[0]["success"])


def test_single_epoch_url_uses_official_healpix_layout() -> None:
    url = single_epoch_rvtab_url(
        "https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0",
        survey="cmx",
        program="other",
        healpix=2152,
    )
    assert url.endswith(
        "/rv_output/240521/healpix/cmx/other/21/2152/"
        "rvtab_spectra-cmx-other-2152.fits"
    )
    with pytest.raises(ValueError, match="excluded"):
        single_epoch_rvtab_url(
            "https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0",
            survey="main",
            program="backup",
            healpix=1,
        )
