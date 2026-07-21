import numpy as np
import pytest

from hou_compact.primary import (
    LOGG_SUN_CGS,
    draw_gspphot_primary_mass,
    mass_from_logg_radius,
    summarize_primary_mass,
)


def test_solar_gravity_and_radius_give_solar_mass() -> None:
    mass = mass_from_logg_radius(LOGG_SUN_CGS, 1.0)
    assert float(mass) == pytest.approx(1.0, rel=1e-12)


def test_mass_scaling_with_radius_squared() -> None:
    masses = mass_from_logg_radius(np.array([LOGG_SUN_CGS, LOGG_SUN_CGS]), [1.0, 2.0])
    assert np.allclose(masses, [1.0, 4.0])


def test_zero_width_quantiles_are_deterministic() -> None:
    samples = draw_gspphot_primary_mass(
        logg_median=LOGG_SUN_CGS,
        logg_lower=LOGG_SUN_CGS,
        logg_upper=LOGG_SUN_CGS,
        radius_median=1.0,
        radius_lower=1.0,
        radius_upper=1.0,
        n_draws=1000,
        random_seed=4,
    )
    assert np.allclose(samples.mass_solar, 1.0)
    summary = summarize_primary_mass(samples)
    assert summary["primary_mass_solar"] == pytest.approx(1.0)
    assert summary["primary_mass_error_solar"] == pytest.approx(0.0)


def test_asymmetric_draw_is_reproducible_and_positive() -> None:
    kwargs = dict(
        logg_median=4.2,
        logg_lower=4.0,
        logg_upper=4.3,
        radius_median=1.4,
        radius_lower=1.1,
        radius_upper=1.8,
        n_draws=2000,
        random_seed=12,
    )
    first = draw_gspphot_primary_mass(**kwargs)
    second = draw_gspphot_primary_mass(**kwargs)
    assert np.array_equal(first.mass_solar, second.mass_solar)
    assert np.all(first.mass_solar > 0)


def test_rejects_non_monotonic_quantiles() -> None:
    with pytest.raises(ValueError, match="lower <= median <= upper"):
        draw_gspphot_primary_mass(
            logg_median=4.0,
            logg_lower=4.2,
            logg_upper=4.3,
            radius_median=1.0,
            radius_lower=0.8,
            radius_upper=1.2,
            n_draws=1000,
        )
