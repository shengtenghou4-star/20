import numpy as np
import pandas as pd
import pytest

from hou_compact.selection_bias import (
    audit_numeric_selection,
    primary_mass_status_mask,
    quantile_bin_selection_rates,
)


def test_numeric_audit_detects_large_shift() -> None:
    frame = pd.DataFrame({"x": [0.0, 0.1, 0.2, 10.0, 10.1, 10.2]})
    mask = np.array([True, True, True, False, False, False])
    result = audit_numeric_selection(frame, field="x", scored_mask=mask)
    assert result.scored_finite_count == 3
    assert result.unscored_finite_count == 3
    assert result.standardized_mean_difference is not None
    assert abs(result.standardized_mean_difference) > 10
    assert result.interpretation == "large_distribution_shift"
    assert result.ks_statistic == pytest.approx(1.0)


def test_numeric_audit_handles_missing_values() -> None:
    frame = pd.DataFrame({"x": [1.0, np.nan, 1.1, np.nan]})
    mask = np.array([True, True, False, False])
    result = audit_numeric_selection(frame, field="x", scored_mask=mask)
    assert result.full_finite_count == 2
    assert result.scored_finite_count == 1
    assert result.unscored_finite_count == 1
    assert result.ks_statistic is None


def test_quantile_bins_report_scored_fraction() -> None:
    frame = pd.DataFrame({"x": np.arange(10, dtype=float)})
    mask = np.array([True] * 5 + [False] * 5)
    bins = quantile_bin_selection_rates(
        frame,
        field="x",
        scored_mask=mask,
        quantiles=(0.0, 0.5, 1.0),
    )
    assert bins["rows"].sum() == 10
    assert bins["scored_rows"].sum() == 5
    assert bins.iloc[0]["scored_fraction"] == 1.0
    assert bins.iloc[1]["scored_fraction"] == 0.0


def test_primary_mass_status_mask_uses_frozen_definition() -> None:
    primary = pd.DataFrame(
        {"status": ["scored", "weak_prior", "input_error", "missing"]}
    )
    assert primary_mass_status_mask(primary).tolist() == [True, True, False, False]


def test_invalid_mask_shape_is_rejected() -> None:
    frame = pd.DataFrame({"x": [1.0, 2.0]})
    with pytest.raises(ValueError, match="scored_mask"):
        audit_numeric_selection(frame, field="x", scored_mask=[True])


def test_invalid_quantiles_are_rejected() -> None:
    frame = pd.DataFrame({"x": [1.0, 2.0]})
    with pytest.raises(ValueError, match="quantiles"):
        quantile_bin_selection_rates(
            frame,
            field="x",
            scored_mask=[True, False],
            quantiles=(0.1, 1.0),
        )
