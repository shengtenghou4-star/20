import math

import pandas as pd
import pytest

from hou_compact.lamost import (
    LamostContractError,
    explode_lrs_multiple_epoch_catalog,
    explode_lrs_multiple_epoch_row,
    join_lrs_spectrum_uncertainties,
    lamost_lmjm_to_utc_mjd,
    parse_exact_int_text,
    parse_hyphen_numeric_list,
)


def test_large_gaia_id_parses_exactly_from_text() -> None:
    value = "6012345678901234567.0"
    parsed = parse_exact_int_text(value, name="gaia_source_id")
    assert parsed == 6_012_345_678_901_234_567


def test_float_identifier_is_rejected_as_potentially_lossy() -> None:
    with pytest.raises(LamostContractError, match="floating point"):
        parse_exact_int_text(6.012345678901234e18, name="gaia_source_id")


def test_hyphen_numeric_list_handles_negative_values() -> None:
    assert parse_hyphen_numeric_list(
        "12.0--8.5-3.0",
        name="rv_list",
    ) == [12.0, -8.5, 3.0]
    assert parse_hyphen_numeric_list(
        "-12.0--8.5",
        name="rv_list",
    ) == [-12.0, -8.5]


def test_lmjm_conversion_matches_official_header_example() -> None:
    # Official example: LMJMLIST=83764590 and DATE-BEG=20:30 Beijing = 12:30 UTC.
    mjd = lamost_lmjm_to_utc_mjd(83_764_590)
    assert mjd == pytest.approx(58_169.520833333336)


def test_explode_multiple_epoch_row() -> None:
    row = {
        "source_id": "LAMOST-HTM-1",
        "gaia_source_id": "6012345678901234567",
        "obs_number": "3",
        "obsid_list": "101-102-103",
        "midmjm_list": "83764590-83766030-83767470",
        "rv_list": "12.0--8.5-3.0",
    }
    epochs = explode_lrs_multiple_epoch_row(row)
    assert epochs["obsid"].tolist() == [101, 102, 103]
    assert epochs["vrad_list_kms"].tolist() == [12.0, -8.5, 3.0]
    assert epochs["observation_count"].eq(3).all()
    assert epochs["source_match_mode"].eq(
        "lamost_dr8_v1_gaia_dr2_exact"
    ).all()
    assert epochs["mjd"].is_monotonic_increasing


def test_explode_rejects_list_length_mismatch() -> None:
    row = {
        "source_id": "LAMOST-HTM-1",
        "gaia_source_id": "1",
        "obs_number": "2",
        "obsid_list": "101-102",
        "midmjm_list": "83764590",
        "rv_list": "12.0-13.0",
    }
    with pytest.raises(LamostContractError, match="lengths disagree"):
        explode_lrs_multiple_epoch_row(row)


def test_catalog_rejects_duplicate_source_obsid() -> None:
    row = {
        "source_id": "LAMOST-HTM-1",
        "gaia_source_id": "1",
        "obs_number": "2",
        "obsid_list": "101-102",
        "midmjm_list": "83764590-83766030",
        "rv_list": "12.0-13.0",
    }
    with pytest.raises(
        LamostContractError,
        match="duplicate DR2-source/obsid",
    ):
        explode_lrs_multiple_epoch_catalog([row, row])


def test_uncertainty_join_marks_only_consistent_rows_scorable() -> None:
    epochs = explode_lrs_multiple_epoch_row(
        {
            "source_id": "LAMOST-HTM-1",
            "gaia_source_id": "1",
            "obs_number": "3",
            "obsid_list": "101-102-103",
            "midmjm_list": "83764590-83766030-83767470",
            "rv_list": "12.0--8.5-3.0",
        }
    )
    spectra = pd.DataFrame(
        {
            "obsid": ["101", "102", "103"],
            "rv": [12.1, -8.4, 8.0],
            "rv_err": [1.0, 0.8, 1.0],
            "snrg": [20.0, 15.0, 10.0],
        }
    )
    joined = join_lrs_spectrum_uncertainties(
        epochs,
        spectra,
        maximum_rv_difference_kms=1.0,
    )
    assert joined["lamost_epoch_status"].tolist() == [
        "scorable",
        "scorable",
        "rv_product_disagreement",
    ]
    assert joined.loc[0, "vrad"] == pytest.approx(12.1)
    assert joined.loc[1, "vrad_err"] == pytest.approx(0.8)


def test_missing_spectrum_uncertainty_cannot_be_scorable() -> None:
    epochs = explode_lrs_multiple_epoch_row(
        {
            "source_id": "LAMOST-HTM-1",
            "gaia_source_id": "1",
            "obs_number": "2",
            "obsid_list": "101-102",
            "midmjm_list": "83764590-83766030",
            "rv_list": "12.0-13.0",
        }
    )
    spectra = pd.DataFrame(
        {
            "obsid": ["101"],
            "rv": [12.0],
            "rv_err": [float("nan")],
        }
    )
    joined = join_lrs_spectrum_uncertainties(epochs, spectra)
    assert joined["lamost_epoch_status"].tolist() == [
        "missing_or_nonfinite_rv_uncertainty",
        "missing_spectrum_obsid_join",
    ]
    assert math.isnan(joined.loc[0, "vrad_err"])
