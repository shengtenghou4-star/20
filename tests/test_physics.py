import math

import pytest

from hou_compact.physics import (
    minimum_companion_mass,
    rv_pairwise_significance,
    rv_variability_chi2,
    spectroscopic_mass_function,
)


def test_mass_function_known_scale() -> None:
    # P=1 day, K1=100 km/s, e=0 gives approximately 0.1036 solar masses.
    value = spectroscopic_mass_function(1.0, 100.0, 0.0)
    assert value == pytest.approx(0.1036, rel=2e-3)


def test_mass_function_decreases_with_eccentricity() -> None:
    circular = spectroscopic_mass_function(10.0, 40.0, 0.0)
    eccentric = spectroscopic_mass_function(10.0, 40.0, 0.6)
    assert eccentric < circular


def test_minimum_companion_mass_inverts_equation() -> None:
    primary = 1.0
    companion = 3.0
    mass_function = companion**3 / (primary + companion) ** 2
    recovered = minimum_companion_mass(primary, mass_function)
    assert recovered == pytest.approx(companion, rel=1e-9)


def test_constant_rv_chi_square() -> None:
    chi2, dof, mean = rv_variability_chi2([10.0, 10.0, 10.0], [1.0, 1.0, 1.0])
    assert chi2 == pytest.approx(0.0)
    assert dof == 2
    assert mean == pytest.approx(10.0)


def test_pairwise_significance() -> None:
    sig = rv_pairwise_significance([0.0, 10.0], [1.0, 1.0])
    assert sig == pytest.approx(10.0 / math.sqrt(2.0))


@pytest.mark.parametrize(
    "args",
    [
        (0.0, 10.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 10.0, -0.1),
        (1.0, 10.0, 1.0),
    ],
)
def test_mass_function_rejects_invalid_inputs(args: tuple[float, float, float]) -> None:
    with pytest.raises(ValueError):
        spectroscopic_mass_function(*args)
