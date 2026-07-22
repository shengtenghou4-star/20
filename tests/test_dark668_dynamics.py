from __future__ import annotations

import math

import pandas as pd
import pytest

from hou_compact.dark668_dynamics import (
    DynamicalAuditConfig,
    candidate_safe_dynamical_summary,
    eggleton_roche_fraction,
    minimum_companion_mass_solar,
    primary_roche_geometry_proxy,
    score_dynamical_consistency,
    spectroscopic_mass_function_solar,
)

_G_SI = 6.67430e-11
_M_SUN_KG = 1.98847e30
_DAY_SECONDS = 86_400.0


def _amplitude_for_mass_function(
    mass_function_solar: float,
    period_days: float,
    eccentricity: float,
) -> float:
    numerator = 2.0 * math.pi * _G_SI * _M_SUN_KG * mass_function_solar
    denominator = (
        period_days * _DAY_SECONDS * (1.0 - eccentricity**2) ** 1.5
    )
    return (numerator / denominator) ** (1.0 / 3.0) / 1_000.0


def test_mass_function_and_minimum_mass_recover_equal_mass_binary() -> None:
    primary_mass = 1.0
    companion_mass = 1.0
    expected_function = companion_mass**3 / (primary_mass + companion_mass) ** 2
    period = 10.0
    eccentricity = 0.2
    amplitude = _amplitude_for_mass_function(
        expected_function,
        period,
        eccentricity,
    )

    observed_function = spectroscopic_mass_function_solar(
        period,
        amplitude,
        eccentricity,
    )
    recovered_mass = minimum_companion_mass_solar(
        observed_function,
        primary_mass,
    )
    assert observed_function == pytest.approx(expected_function, rel=1e-10)
    assert recovered_mass == pytest.approx(companion_mass, rel=1e-10)


def test_minimum_companion_mass_increases_with_mass_function() -> None:
    low = minimum_companion_mass_solar(0.1, 1.2)
    high = minimum_companion_mass_solar(2.0, 1.2)
    assert 0 < low < high


def test_roche_geometry_proxy_is_finite_for_detached_system() -> None:
    geometry = primary_roche_geometry_proxy(
        period_days=30.0,
        eccentricity=0.1,
        primary_mass_solar=1.0,
        minimum_companion_mass=5.0,
        primary_radius_solar=1.0,
    )
    assert geometry["periastron_separation_rsun"] > 0
    assert geometry["primary_roche_lobe_periastron_rsun_proxy"] > 0
    assert 0 < geometry["primary_roche_fill_factor_proxy"] < 1
    assert 0 < eggleton_roche_fraction(0.2) < 1


def test_score_dynamical_consistency_promotes_strong_massive_case() -> None:
    primary_mass = 1.0
    companion_mass = 5.0
    mass_function = companion_mass**3 / (primary_mass + companion_mass) ** 2
    period = 20.0
    eccentricity = 0.15
    amplitude = _amplitude_for_mass_function(
        mass_function,
        period,
        eccentricity,
    )
    candidates = pd.DataFrame(
        {
            "source_id": [123],
            "mass": [primary_mass],
            "radius": [1.0],
            "fit_companion_mass": [5.0],
            "fit_companion_mass_errup": [0.5],
            "fit_companion_mass_errlow": [0.5],
            "population": ["MS"],
        }
    )
    kepler = pd.DataFrame(
        {
            "source_id": [123],
            "status": ["scored"],
            "period_days": [period],
            "period_error_days": [0.02],
            "semi_amplitude_kms": [amplitude],
            "semi_amplitude_error_kms": [0.02],
            "eccentricity": [eccentricity],
            "eccentricity_error": [0.002],
            "delta_bic_circular_minus_keplerian": [12.0],
            "reduced_chi2": [1.1],
        }
    )
    scored = score_dynamical_consistency(
        candidates,
        kepler,
        DynamicalAuditConfig(maximum_roche_fill_proxy=0.9),
    )
    row = scored.iloc[0]
    assert row["status"] == "scored"
    assert row["minimum_companion_mass_solar"] == pytest.approx(5.0, rel=1e-8)
    assert row["minimum_companion_mass_lower_solar"] > 3.0
    assert bool(row["strong_followup_gate"])
    assert row["mass_consistency_status"] == "uncertainty_intervals_not_disjoint"


def test_non_scored_kepler_row_is_retained_without_physical_claim() -> None:
    candidates = pd.DataFrame(
        {
            "source_id": [7],
            "mass": [1.0],
            "radius": [1.0],
            "fit_companion_mass": [4.0],
            "fit_companion_mass_errup": [1.0],
            "fit_companion_mass_errlow": [1.0],
        }
    )
    kepler = pd.DataFrame(
        {
            "source_id": [7],
            "status": ["not_preselected"],
            "period_days": [math.nan],
            "semi_amplitude_kms": [math.nan],
            "eccentricity": [math.nan],
            "delta_bic_circular_minus_keplerian": [math.nan],
            "reduced_chi2": [math.nan],
        }
    )
    scored = score_dynamical_consistency(candidates, kepler)
    assert scored.loc[0, "status"] == "not_keplerian_scored"


def test_candidate_safe_summary_contains_no_identifiers() -> None:
    scores = pd.DataFrame(
        {
            "source_id": [987654321],
            "status": ["scored"],
            "minimum_companion_mass_solar": [5.0],
            "minimum_companion_mass_lower_solar": [4.5],
            "mass_function_solar": [3.0],
            "mass_consistency_status": ["uncertainty_intervals_not_disjoint"],
            "primary_roche_fill_factor_proxy": [0.1],
            "point_followup_gate": [True],
            "strong_followup_gate": [True],
            "uncertainty_bracket_available": [True],
        }
    )
    summary = candidate_safe_dynamical_summary(scores)
    text = str(summary)
    assert "987654321" not in text
    assert summary["followup_gate_counts"]["strong_followup"] == 1
