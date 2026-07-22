from __future__ import annotations

import math

import pandas as pd

from hou_compact.dark668_lamost import (
    candidate_safe_join_summary,
    join_and_standardize_tap_rv,
)


def _epochs() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": [1001, 1001, 2002, 3003],
            "dr2_source_id": [11, 11, 22, 33],
            "lamost_source_id": ["a", "a", "b", "c"],
            "obsid": [1, 2, 3, 4],
            "lmjm": [85000000, 85001000, 85002000, 85003000],
            "mjd": [59000.0, 59001.0, 59002.0, 59003.0],
            "vrad_list_kms": [10.0, 20.0, 30.0, 40.0],
            "rv_list_status": ["measured_without_uncertainty"] * 4,
            "observation_index": [0, 1, 0, 0],
            "observation_count": [2, 2, 2, 2],
        }
    )


def test_join_and_standardize_fails_closed_on_quality_metadata() -> None:
    spectra = pd.DataFrame(
        {
            "obsid": [1, 2, 3, 4],
            "rv": [10.2, 25.0, 30.1, 40.0],
            "rv_err": [1.0, 1.0, 2.0, 1.5],
            "snrg": [20.0, 20.0, 15.0, 30.0],
            "snri": [25.0, 25.0, 18.0, 35.0],
            "fibermask": [0.0, 0.0, 1.0, math.nan],
        }
    )
    result = join_and_standardize_tap_rv(_epochs(), spectra)
    statuses = dict(zip(result["obsid"], result["lamost_epoch_status"], strict=True))
    assert statuses == {
        1: "scorable",
        2: "rv_product_disagreement",
        3: "fibermask_nonzero",
        4: "missing_fibermask",
    }
    assert result.loc[result["obsid"].eq(1), "success"].item()
    assert not result.loc[result["obsid"].ne(1), "success"].any()
    assert result["program"].eq("lamost_lrs_dr8_v1_tap").all()
    assert result["survey"].eq("lamost_dr8").all()


def test_missing_fibermask_column_blocks_otherwise_scorable_rows() -> None:
    spectra = pd.DataFrame(
        {
            "obsid": [1],
            "rv": [10.0],
            "rv_err": [1.0],
            "snrg": [20.0],
            "snri": [20.0],
        }
    )
    result = join_and_standardize_tap_rv(_epochs().head(1), spectra)
    assert result.iloc[0]["lamost_epoch_status"] == "missing_fibermask"
    assert not result.iloc[0]["success"]


def test_candidate_safe_join_summary_contains_counts_only() -> None:
    spectra = pd.DataFrame(
        {
            "obsid": [1, 2, 3, 4],
            "rv": [10.0, 20.0, 30.0, 40.0],
            "rv_err": [1.0, 1.0, 1.0, 1.0],
            "snrg": [20.0] * 4,
            "snri": [20.0] * 4,
            "fibermask": [0] * 4,
        }
    )
    result = join_and_standardize_tap_rv(_epochs(), spectra)
    summary = candidate_safe_join_summary(result)
    assert summary["epoch_rows"] == 4
    assert summary["scorable_epoch_rows"] == 4
    assert summary["scorable_source_count"] == 3
    assert summary["scorable_source_visit_threshold_counts"]["ge_2"] == 1
    assert "source_id" not in summary
    assert "1001" not in str(summary)
