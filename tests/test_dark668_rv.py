from __future__ import annotations

import math

import numpy as np
import pandas as pd

from hou_compact.dark668_rv import (
    PeriodPriorConfig,
    candidate_safe_period_summary,
    fit_circular_velocity,
    period_prior_grid,
    scan_period_prior,
    score_period_prior_candidates,
)


def _epochs(
    source_id: int,
    mjd: np.ndarray,
    velocity: np.ndarray,
    error: float = 1.0,
) -> pd.DataFrame:
    count = len(mjd)
    return pd.DataFrame(
        {
            "source_id": [source_id] * count,
            "mjd": mjd,
            "vrad": velocity,
            "vrad_err": [error] * count,
            "success": [True] * count,
            "rvs_warn": [0] * count,
            "fiberstatus": [0] * count,
            "sn_b": [20.0] * count,
            "sn_r": [25.0] * count,
            "sn_z": [math.nan] * count,
            "program": ["lamost_lrs_dr8_v1"] * count,
        }
    )


def test_period_prior_grid_contains_published_period() -> None:
    config = PeriodPriorConfig(period_grid_size=32, permutation_repetitions=0)
    grid = period_prior_grid(100.0, 20.0, 10.0, config)
    assert np.any(np.isclose(grid, 100.0))
    assert grid[0] == 70.0
    assert grid[-1] == 160.0
    assert np.all(np.diff(grid) > 0)


def test_fixed_period_circular_fit_recovers_amplitude() -> None:
    mjd = np.asarray([0.0, 1.3, 2.7, 4.2, 6.1, 7.4, 9.0, 11.5])
    period = 10.0
    velocity = 30.0 + 12.0 * np.sin(2.0 * np.pi * mjd / period)
    error = np.ones_like(mjd)
    fit = fit_circular_velocity(mjd, velocity, error, period)
    _, sine, cosine = fit.coefficients
    assert fit.chi2 < 1e-20
    assert math.isclose(math.hypot(sine, cosine), 12.0, rel_tol=1e-10)


def test_period_scan_prefers_true_period_and_penalizes_constant() -> None:
    mjd = np.asarray(
        [0.0, 1.7, 4.4, 7.9, 12.3, 18.2, 27.1, 38.0, 51.4, 69.2]
    )
    period = 13.0
    velocity = 5.0 + 18.0 * np.sin(2.0 * np.pi * mjd / period + 0.4)
    error = np.full_like(mjd, 1.5)
    periods = np.geomspace(8.0, 20.0, 160)
    periods = np.unique(np.concatenate([periods, [period]]))
    result = scan_period_prior(mjd, velocity, error, periods)
    assert abs(result["best_period_days"] - period) / period < 0.02
    assert result["delta_bic_constant_minus_periodic"] > 100.0

    constant = scan_period_prior(mjd, np.full_like(mjd, 5.0), error, periods)
    assert constant["delta_bic_constant_minus_periodic"] < 0.0


def test_candidate_scoring_recovers_coherent_period() -> None:
    source_id = 123456789012345678
    mjd = np.asarray(
        [
            59000.0,
            59001.8,
            59004.7,
            59009.1,
            59015.0,
            59022.4,
            59031.8,
            59043.3,
            59056.9,
            59072.6,
            59090.4,
            59110.1,
        ]
    )
    period = 17.0
    velocity = 40.0 + 25.0 * np.sin(2.0 * np.pi * (mjd - mjd[0]) / period + 0.2)
    candidates = pd.DataFrame(
        {
            "source_id": [source_id, source_id + 1],
            "fit_period": [period, 20.0],
            "fit_period_errup": [1.0, 2.0],
            "fit_period_errlow": [1.0, 2.0],
            "population": ["RGB", "MS"],
            "priority_rank": [1, 2],
        }
    )
    epochs = pd.concat(
        [
            _epochs(source_id, mjd, velocity),
            _epochs(source_id + 1, np.asarray([59000.0, 59005.0, 59010.0]), np.zeros(3)),
        ],
        ignore_index=True,
    )
    config = PeriodPriorConfig(
        minimum_independent_visits=5,
        period_grid_size=96,
        permutation_repetitions=39,
        base_seed=7,
    )
    scores = score_period_prior_candidates(candidates, epochs, config)
    recovered = scores.loc[scores["source_id"].eq(source_id)].iloc[0]
    sparse = scores.loc[scores["source_id"].eq(source_id + 1)].iloc[0]
    assert recovered["status"] == "scored"
    assert abs(recovered["best_period_days"] - period) / period < 0.05
    assert recovered["delta_bic_constant_minus_periodic"] > 50.0
    assert recovered["permutation_false_alarm_probability"] <= 0.05
    assert sparse["status"] == "insufficient_independent_visits"


def test_candidate_safe_summary_has_aggregates_only() -> None:
    scores = pd.DataFrame(
        {
            "source_id": [111, 222],
            "status": ["scored", "insufficient_independent_visits"],
            "delta_bic_constant_minus_periodic": [12.0, math.nan],
            "permutation_false_alarm_probability": [0.02, math.nan],
            "n_independent_visits": [8, 2],
        }
    )
    summary = candidate_safe_period_summary(scores)
    assert summary["score_rows"] == 2
    assert summary["scored_rows"] == 1
    assert summary["joint_followup_counts"]["delta_bic_ge_10_and_fap_le_0.05"] == 1
    assert "source_id" not in summary
    assert "111" not in str(summary)
