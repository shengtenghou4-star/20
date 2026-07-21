import numpy as np
import pytest

from hou_compact.masses import (
    draw_mass_posterior,
    draw_standard_sb1_products,
    summarize_mass_posterior,
)
from hou_compact.physics import spectroscopic_mass_function


def test_zero_error_edge_on_recovers_exact_mass() -> None:
    primary = 1.0
    companion = 3.0
    mass_function = companion**3 / (primary + companion) ** 2
    # Invert the mass-function formula to construct K1 at P=10 d and e=0.
    base = spectroscopic_mass_function(10.0, 1.0, 0.0)
    k1 = (mass_function / base) ** (1.0 / 3.0)
    samples = draw_mass_posterior(
        period_days=10.0,
        period_error_days=0.0,
        k1_kms=k1,
        k1_error_kms=0.0,
        eccentricity=0.0,
        eccentricity_error=0.0,
        primary_mass_solar=primary,
        primary_mass_error_solar=0.0,
        n_draws=1000,
        inclination_mode="edge_on",
        random_seed=7,
    )
    assert np.allclose(samples.companion_mass_solar, companion, rtol=1e-9)


def test_fixed_inclination_recovers_exact_mass() -> None:
    primary = 1.2
    companion = 5.0
    inclination_deg = 30.0
    sine = np.sin(np.radians(inclination_deg))
    mass_function = companion**3 * sine**3 / (primary + companion) ** 2
    base = spectroscopic_mass_function(20.0, 1.0, 0.2)
    k1 = (mass_function / base) ** (1.0 / 3.0)
    samples = draw_mass_posterior(
        period_days=20.0,
        period_error_days=0.0,
        k1_kms=k1,
        k1_error_kms=0.0,
        eccentricity=0.2,
        eccentricity_error=0.0,
        primary_mass_solar=primary,
        primary_mass_error_solar=0.0,
        n_draws=1000,
        inclination_mode="fixed",
        inclination_deg=inclination_deg,
        random_seed=3,
    )
    assert np.allclose(samples.companion_mass_solar, companion, rtol=1e-9)


def test_isotropic_sensitivity_exceeds_minimum_mass_median() -> None:
    products = draw_standard_sb1_products(
        period_days=10.0,
        period_error_days=0.1,
        k1_kms=60.0,
        k1_error_kms=1.0,
        eccentricity=0.1,
        eccentricity_error=0.02,
        primary_mass_solar=1.0,
        primary_mass_error_solar=0.1,
        n_draws=5000,
        random_seed=11,
    )
    minimum_median = products["minimum_mass"]["companion_mass_quantiles_solar"][3]
    isotropic_median = products["isotropic_sensitivity"][
        "companion_mass_quantiles_solar"
    ][3]
    assert isotropic_median > minimum_median


def test_posterior_is_reproducible_for_fixed_seed() -> None:
    kwargs = dict(
        period_days=4.0,
        period_error_days=0.1,
        k1_kms=30.0,
        k1_error_kms=2.0,
        eccentricity=0.2,
        eccentricity_error=0.05,
        primary_mass_solar=0.9,
        primary_mass_error_solar=0.1,
        n_draws=1000,
        inclination_mode="isotropic",
        random_seed=99,
    )
    first = draw_mass_posterior(**kwargs)
    second = draw_mass_posterior(**kwargs)
    assert np.array_equal(first.companion_mass_solar, second.companion_mass_solar)


def test_summary_reports_threshold_probabilities() -> None:
    samples = draw_mass_posterior(
        period_days=10.0,
        period_error_days=0.0,
        k1_kms=100.0,
        k1_error_kms=0.0,
        eccentricity=0.0,
        eccentricity_error=0.0,
        primary_mass_solar=1.0,
        primary_mass_error_solar=0.0,
        n_draws=1000,
        inclination_mode="edge_on",
    )
    summary = summarize_mass_posterior(samples, thresholds_solar=(1.0, 10.0))
    assert "probability_m2_gt_1p0_solar" in summary
    assert "probability_m2_gt_10p0_solar" in summary


def test_rejects_too_few_draws() -> None:
    with pytest.raises(ValueError, match="at least 100"):
        draw_mass_posterior(
            period_days=1.0,
            period_error_days=0.1,
            k1_kms=10.0,
            k1_error_kms=1.0,
            eccentricity=0.0,
            eccentricity_error=0.0,
            primary_mass_solar=1.0,
            primary_mass_error_solar=0.1,
            n_draws=10,
        )
