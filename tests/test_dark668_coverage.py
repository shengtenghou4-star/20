from __future__ import annotations

import math

import pandas as pd

from hou_compact.dark668_coverage import (
    candidate_safe_coverage_summary,
    summarize_period_coverage,
)


def test_period_coverage_summary_preserves_all_candidates() -> None:
    candidates = pd.DataFrame(
        {
            "source_id": [101, 202, 303],
            "fit_period": [10.0, 20.0, 30.0],
            "population": ["RGB", "MS", "RGB"],
            "priority_rank": [1, 2, 3],
        }
    )
    epochs = pd.DataFrame(
        {
            "source_id": [101, 101, 101, 202],
            "mjd": [59000.0, 59005.0, 59010.0, 59001.0],
            "vrad": [10.0, 30.0, 10.0, -4.0],
        }
    )
    result = summarize_period_coverage(candidates, epochs)
    assert len(result) == 3

    first = result.loc[result["source_id"].eq(101)].iloc[0]
    assert first["status"] == "coverage_summarized"
    assert first["n_usable_epochs"] == 3
    assert first["baseline_days"] == 10.0
    assert first["period_cycles_spanned"] == 1.0
    assert first["rv_range_kms"] == 20.0
    assert 0.0 <= first["phase_coverage"] <= 1.0

    second = result.loc[result["source_id"].eq(202)].iloc[0]
    assert second["status"] == "single_usable_epoch"
    assert second["phase_coverage"] == 0.0

    third = result.loc[result["source_id"].eq(303)].iloc[0]
    assert third["status"] == "no_usable_epochs"


def test_nonfinite_epoch_rows_are_rejected_from_usable_counts() -> None:
    candidates = pd.DataFrame({"source_id": [1], "fit_period": [5.0]})
    epochs = pd.DataFrame(
        {
            "source_id": [1, 1, 1],
            "mjd": [59000.0, math.nan, 59003.0],
            "vrad": [1.0, 2.0, math.nan],
        }
    )
    result = summarize_period_coverage(candidates, epochs)
    row = result.iloc[0]
    assert row["n_raw_epoch_rows"] == 3
    assert row["n_usable_epochs"] == 1
    assert row["status"] == "single_usable_epoch"


def test_candidate_safe_coverage_summary_contains_only_aggregates() -> None:
    coverage = pd.DataFrame(
        {
            "source_id": [111, 222],
            "population": ["RGB", "MS"],
            "status": ["coverage_summarized", "no_usable_epochs"],
            "n_usable_epochs": [6, 0],
            "period_cycles_spanned": [2.5, math.nan],
            "phase_coverage": [0.7, math.nan],
            "rv_robust_amplitude_kms": [55.0, math.nan],
        }
    )
    summary = candidate_safe_coverage_summary(coverage)
    assert summary["candidate_rows"] == 2
    assert summary["usable_epoch_threshold_counts"]["ge_5"] == 1
    assert summary["period_cycles_threshold_counts"]["ge_2"] == 1
    assert summary["phase_coverage_threshold_counts"]["ge_0.6"] == 1
    assert summary["raw_amplitude_threshold_counts"]["ge_50_kms"] == 1
    assert summary["population_coverage_counts"] == {"RGB": 1}
    assert "source_id" not in summary
    assert "111" not in str(summary)
