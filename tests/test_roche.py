import numpy as np
import pytest

from hou_compact.roche import (
    eggleton_primary_roche_fraction,
    infer_roche_geometry_posterior,
    orbital_separation_solar_radii,
    primary_roche_lobe_radius_solar,
)


def test_eggleton_equal_mass_fraction() -> None:
    value = float(eggleton_primary_roche_fraction(1.0))
    assert value == pytest.approx(0.3789205, rel=1e-6)


def test_one_year_one_solar_mass_separation_scale() -> None:
    separation = float(orbital_separation_solar_radii(365.256, 1.0, 1e-12))
    assert separation == pytest.approx(215.03, rel=2e-3)


def test_eccentric_periastron_roche_lobe_is_smaller() -> None:
    circular = float(primary_roche_lobe_radius_solar(20.0, 0.0, 1.0, 1.0))
    eccentric = float(primary_roche_lobe_radius_solar(20.0, 0.5, 1.0, 1.0))
    assert eccentric == pytest.approx(0.5 * circular)


def test_detached_system_is_classified_consistent() -> None:
    result = infer_roche_geometry_posterior(
        period_days=20.0,
        period_error_days=0.01,
        eccentricity=0.0,
        eccentricity_error=0.005,
        primary_mass_q16_solar=0.95,
        primary_mass_q50_solar=1.0,
        primary_mass_q84_solar=1.05,
        companion_mass_q16_solar=0.9,
        companion_mass_q50_solar=1.0,
        companion_mass_q84_solar=1.1,
        primary_radius_q16_solar=0.95,
        primary_radius_q50_solar=1.0,
        primary_radius_q84_solar=1.05,
        n_draws=5000,
        random_seed=1,
    )
    assert result.status == "detached_geometry_consistent"
    assert result.filling_q84 < 0.2
    assert result.probability_filling_gt_1p0 == 0.0


def test_short_period_giant_is_geometry_inconsistent() -> None:
    result = infer_roche_geometry_posterior(
        period_days=1.22,
        period_error_days=0.01,
        eccentricity=0.02,
        eccentricity_error=0.01,
        primary_mass_q16_solar=5.5,
        primary_mass_q50_solar=6.0,
        primary_mass_q84_solar=6.5,
        companion_mass_q16_solar=3.8,
        companion_mass_q50_solar=4.2,
        companion_mass_q84_solar=4.6,
        primary_radius_q16_solar=14.0,
        primary_radius_q50_solar=16.0,
        primary_radius_q84_solar=18.0,
        n_draws=5000,
        random_seed=2,
    )
    assert result.status == "geometry_inconsistent"
    assert result.filling_q16 > 1.0
    assert result.probability_filling_gt_1p0 > 0.95


def test_invalid_quantiles_are_rejected() -> None:
    with pytest.raises(ValueError, match="quantiles"):
        infer_roche_geometry_posterior(
            period_days=10.0,
            period_error_days=0.1,
            eccentricity=0.0,
            eccentricity_error=0.01,
            primary_mass_q16_solar=1.2,
            primary_mass_q50_solar=1.0,
            primary_mass_q84_solar=1.1,
            companion_mass_q16_solar=1.0,
            companion_mass_q50_solar=1.1,
            companion_mass_q84_solar=1.2,
            primary_radius_q16_solar=1.0,
            primary_radius_q50_solar=1.1,
            primary_radius_q84_solar=1.2,
            n_draws=1000,
        )


def test_vectorized_separation_validation() -> None:
    values = orbital_separation_solar_radii(
        np.array([1.0, 10.0]),
        np.array([1.0, 2.0]),
        np.array([1.0, 3.0]),
    )
    assert values.shape == (2,)
    assert values[1] > values[0]
