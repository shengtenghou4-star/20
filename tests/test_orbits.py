import math

import numpy as np

from hou_compact.orbits import (
    fit_systemic_velocity,
    gaia_periastron_mjd,
    gaia_sb1_velocity_shape,
    sb1_velocity_shape,
    solve_kepler,
)


def test_kepler_solver_residual_for_high_eccentricity() -> None:
    mean = np.linspace(-math.pi, math.pi, 101)
    eccentric = solve_kepler(mean, 0.95)
    residual = eccentric - 0.95 * np.sin(eccentric) - mean
    assert np.max(np.abs(residual)) < 1e-11


def test_circular_velocity_has_expected_quadrature() -> None:
    times = np.array([100.0, 102.5, 105.0, 107.5])
    shape = sb1_velocity_shape(
        times,
        period_days=10.0,
        periastron_mjd=100.0,
        eccentricity=0.0,
        arg_periastron_deg=0.0,
        semi_amplitude_kms=20.0,
    )
    assert np.allclose(shape, [20.0, 0.0, -20.0, 0.0], atol=1e-10)


def test_gaia_circular_null_convention() -> None:
    periastron = gaia_periastron_mjd(2016.0, 0.0)
    shape = gaia_sb1_velocity_shape(
        [periastron],
        ref_epoch_jyear=2016.0,
        period_days=3.0,
        t_periastron_days=0.0,
        eccentricity=None,
        arg_periastron_deg=None,
        semi_amplitude_kms=7.0,
    )
    assert np.allclose(shape, [7.0], atol=1e-10)


def test_fit_systemic_velocity_recovers_offset() -> None:
    shape = np.array([10.0, -10.0, 5.0, -5.0])
    observed = shape + 23.5
    fit = fit_systemic_velocity(observed, np.ones(4), shape)
    assert abs(fit.systemic_velocity_kms - 23.5) < 1e-12
    assert fit.chi2 < 1e-20
    assert fit.degrees_of_freedom == 3
