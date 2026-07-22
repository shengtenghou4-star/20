from __future__ import annotations

import math

import numpy as np
import pandas as pd

from hou_compact.dark668_kepler import (
    KeplerianConfig,
    candidate_safe_keplerian_summary,
    fit_keplerian_period_prior,
    keplerian_velocity,
    score_keplerian_candidates,
    solve_kepler_equation,
)


def _epochs(source_id: int, mjd: np.ndarray, velocity: np.ndarray) -> pd.DataFrame:
    count = len(mjd)
    return pd.DataFrame(
        {
            "source_id": [source_id] * count,
            "mjd": mjd,
            "vrad": velocity,
            "vrad_err": [1.0] * count,
            "success": [True] * count,
            "rvs_warn": [0] * count,
            "fiberstatus": [0] * count,
            "sn_b": [25.0] * count,
            "sn_r": [30.0] * count,
            "sn_z": [math.nan] * count,
            "program": ["lamost_lrs_dr8_v1_tap"] * count,
        }
    )


def test_kepler_solver_satisfies_equation_modulo_full_revolutions() -> None:
    mean = np.linspace(-3.0 * np.pi, 3.0 * np.pi, 301)
    eccentricity = 0.92
    eccentric = solve_kepler_equation(mean, eccentricity)
    residual = eccentric - eccentricity * np.sin(eccentric) - mean
    wrapped_residual = np.remainder(residual + np.pi, 2.0 * np.pi) - np.pi
    assert np.max(np.abs(wrapped_residual)) < 1e-10


def test_circular_limit_matches_cosine_form() -> None:
    mjd = np.asarray([0.0, 1.0, 2.5, 5.0, 8.0])
    period = 12.0
    gamma = 7.0
    amplitude = 15.0
    omega = 0.4
    mean_zero = -0.2
    model = keplerian_velocity(
        mjd,
        period_days=period,
        semi_amplitude_kms=amplitude,
        eccentricity=0.0,
        omega_radians=omega,
        mean_anomaly_reference_radians=mean_zero,
        systemic_velocity_kms=gamma,
        reference_mjd=0.0,
    )
    expected = gamma + amplitude * np.cos(
        mean_zero + 2.0 * np.pi * mjd / period + omega
    )
    assert np.allclose(model, expected, atol=1e-11)


def test_multistart_keplerian_fit_recovers_synthetic_eccentric_signal() -> None:
    source_id = 987654321012345678
    mjd = np.asarray(
        [
            59000.0,
            59002.3,
            59005.9,
            59010.8,
            59017.1,
            59025.0,
            59034.6,
            59046.1,
            59059.5,
            59075.0,
            59092.7,
            59112.6,
            59134.8,
            59159.3,
        ]
    )
    truth = {
        "period_days": 23.0,
        "semi_amplitude_kms": 32.0,
        "eccentricity": 0.48,
        "omega_radians": 0.7,
        "mean_anomaly_reference_radians": -0.9,
        "systemic_velocity_kms": 18.0,
    }
    velocity = keplerian_velocity(
        mjd,
        **truth,
        reference_mjd=float(mjd.min()),
    )
    config = KeplerianConfig(
        minimum_independent_visits=7,
        period_grid_size=96,
        random_starts=20,
        maximum_function_evaluations=2500,
        base_seed=17,
    )
    result = fit_keplerian_period_prior(
        mjd,
        velocity,
        np.full_like(mjd, 1.0),
        central_period_days=23.0,
        period_error_up_days=2.0,
        period_error_low_days=2.0,
        source_id=source_id,
        config=config,
    )
    assert abs(result["period_days"] - 23.0) / 23.0 < 0.02
    assert abs(result["eccentricity"] - 0.48) < 0.08
    assert abs(result["semi_amplitude_kms"] - 32.0) / 32.0 < 0.08
    assert result["delta_bic_circular_minus_keplerian"] > 10.0
    assert result["reduced_chi2"] < 1e-6
    assert result["optimization_starts_successful"] >= 1


def test_candidate_scoring_respects_circular_preselection_and_visit_gate() -> None:
    selected_id = 101
    rejected_id = 202
    sparse_id = 303
    mjd = np.asarray(
        [59000.0, 59003.0, 59007.0, 59012.0, 59018.0, 59025.0, 59033.0, 59042.0]
    )
    selected_velocity = keplerian_velocity(
        mjd,
        period_days=19.0,
        semi_amplitude_kms=25.0,
        eccentricity=0.35,
        omega_radians=0.5,
        mean_anomaly_reference_radians=-0.3,
        systemic_velocity_kms=10.0,
        reference_mjd=float(mjd.min()),
    )
    candidates = pd.DataFrame(
        {
            "source_id": [selected_id, rejected_id, sparse_id],
            "fit_period": [19.0, 19.0, 19.0],
            "fit_period_errup": [2.0, 2.0, 2.0],
            "fit_period_errlow": [2.0, 2.0, 2.0],
            "population": ["RGB", "MS", "RGB"],
        }
    )
    epochs = pd.concat(
        [
            _epochs(selected_id, mjd, selected_velocity),
            _epochs(rejected_id, mjd, selected_velocity),
            _epochs(sparse_id, mjd[:4], selected_velocity[:4]),
        ],
        ignore_index=True,
    )
    circular = pd.DataFrame(
        {
            "source_id": [selected_id, rejected_id, sparse_id],
            "status": ["scored", "scored", "scored"],
            "delta_bic_constant_minus_periodic": [30.0, 2.0, 30.0],
        }
    )
    config = KeplerianConfig(
        minimum_independent_visits=7,
        minimum_circular_delta_bic=6.0,
        period_grid_size=64,
        random_starts=8,
        maximum_function_evaluations=1500,
        base_seed=3,
    )
    scores = score_keplerian_candidates(candidates, epochs, circular, config)
    status = dict(zip(scores["source_id"], scores["status"], strict=True))
    assert status[selected_id] == "scored"
    assert status[rejected_id] == "not_preselected"
    assert status[sparse_id] == "insufficient_independent_visits"


def test_candidate_safe_summary_contains_only_aggregate_counts() -> None:
    scores = pd.DataFrame(
        {
            "source_id": [111, 222, 333],
            "status": ["scored", "scored", "not_preselected"],
            "delta_bic_circular_minus_keplerian": [8.0, -1.0, math.nan],
            "eccentricity": [0.6, 0.1, math.nan],
            "reduced_chi2": [1.2, 3.0, math.nan],
            "covariance_available": [True, False, False],
        }
    )
    summary = candidate_safe_keplerian_summary(scores)
    assert summary["score_rows"] == 3
    assert summary["scored_rows"] == 2
    assert summary["keplerian_over_circular_threshold_counts"]["delta_bic_ge_6"] == 1
    assert summary["eccentricity_bin_counts"]["ge_0.5"] == 1
    assert summary["fit_quality_counts"]["covariance_available"] == 1
    assert "source_id" not in summary
    assert "111" not in str(summary)
