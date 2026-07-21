"""Physics and quality-control primitives for HOU-COMPACT.

The functions here are deliberately small, deterministic, and independently testable.
They do not assign astrophysical labels. They only calculate quantities used later in
candidate validation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

_G_SI = 6.67430e-11
_M_SUN_KG = 1.98847e30
_DAY_S = 86400.0
_KM_S_TO_M_S = 1000.0


def spectroscopic_mass_function(
    period_days: float,
    k1_kms: float,
    eccentricity: float = 0.0,
) -> float:
    """Return the single-lined spectroscopic mass function in solar masses.

    f(M) = P K1^3 (1 - e^2)^(3/2) / (2 pi G)
    """
    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError("period_days must be finite and positive")
    if not math.isfinite(k1_kms) or k1_kms <= 0:
        raise ValueError("k1_kms must be finite and positive")
    if not math.isfinite(eccentricity) or not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must be finite and satisfy 0 <= e < 1")

    period_s = period_days * _DAY_S
    k1_ms = k1_kms * _KM_S_TO_M_S
    f_kg = (
        period_s
        * k1_ms**3
        * (1.0 - eccentricity**2) ** 1.5
        / (2.0 * math.pi * _G_SI)
    )
    return f_kg / _M_SUN_KG


def companion_mass_from_mass_function(
    primary_mass_solar: float,
    mass_function_solar: float,
    sin_inclination: float = 1.0,
    *,
    relative_tolerance: float = 1e-10,
    max_iterations: int = 256,
) -> float:
    """Solve the SB1 mass-function equation for the positive companion mass.

    The root satisfies

        f = (M2^3 sin(i)^3) / (M1 + M2)^2.

    A monotonic bisection solver avoids optimizer-dependent failures.
    """
    if not math.isfinite(primary_mass_solar) or primary_mass_solar <= 0:
        raise ValueError("primary_mass_solar must be finite and positive")
    if not math.isfinite(mass_function_solar) or mass_function_solar <= 0:
        raise ValueError("mass_function_solar must be finite and positive")
    if not math.isfinite(sin_inclination) or not 0 < sin_inclination <= 1:
        raise ValueError("sin_inclination must be finite and in (0, 1]")
    if not math.isfinite(relative_tolerance) or relative_tolerance <= 0:
        raise ValueError("relative_tolerance must be finite and positive")
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")

    sin_cubed = sin_inclination**3

    def residual(m2: float) -> float:
        return m2**3 * sin_cubed / (primary_mass_solar + m2) ** 2 - mass_function_solar

    low = 0.0
    high = max(1.0, primary_mass_solar, mass_function_solar / sin_cubed)
    while residual(high) < 0:
        high *= 2.0
        if high > 1e8:
            raise RuntimeError("failed to bracket companion-mass root")

    for _ in range(max_iterations):
        midpoint = 0.5 * (low + high)
        if residual(midpoint) > 0:
            high = midpoint
        else:
            low = midpoint
        if high - low <= relative_tolerance * max(1.0, midpoint):
            return 0.5 * (low + high)

    raise RuntimeError("companion_mass_from_mass_function did not converge")


def minimum_companion_mass(
    primary_mass_solar: float,
    mass_function_solar: float,
    *,
    relative_tolerance: float = 1e-10,
    max_iterations: int = 256,
) -> float:
    """Return the edge-on minimum companion mass, with sin(i)=1."""
    return companion_mass_from_mass_function(
        primary_mass_solar,
        mass_function_solar,
        1.0,
        relative_tolerance=relative_tolerance,
        max_iterations=max_iterations,
    )


def rv_variability_chi2(
    velocities_kms: Sequence[float],
    errors_kms: Sequence[float],
) -> tuple[float, int, float]:
    """Return chi-square, degrees of freedom, and weighted mean for constant RV.

    This is a screening statistic only. Epoch correlations and survey systematics must
    be handled before interpreting the value astrophysically.
    """
    velocities = np.asarray(velocities_kms, dtype=float)
    errors = np.asarray(errors_kms, dtype=float)

    if velocities.ndim != 1 or errors.ndim != 1 or velocities.size != errors.size:
        raise ValueError("velocities and errors must be one-dimensional arrays of equal length")
    if velocities.size < 2:
        raise ValueError("at least two RV epochs are required")
    if not np.all(np.isfinite(velocities)):
        raise ValueError("velocities must all be finite")
    if not np.all(np.isfinite(errors)) or np.any(errors <= 0):
        raise ValueError("errors must all be finite and positive")

    weights = 1.0 / errors**2
    weighted_mean = float(np.sum(weights * velocities) / np.sum(weights))
    chi2 = float(np.sum(((velocities - weighted_mean) / errors) ** 2))
    return chi2, int(velocities.size - 1), weighted_mean


def rv_pairwise_significance(
    velocities_kms: Sequence[float],
    errors_kms: Sequence[float],
) -> float:
    """Return the largest pairwise RV difference in combined-error sigma units."""
    velocities = np.asarray(velocities_kms, dtype=float)
    errors = np.asarray(errors_kms, dtype=float)

    if velocities.ndim != 1 or errors.ndim != 1 or velocities.size != errors.size:
        raise ValueError("velocities and errors must be one-dimensional arrays of equal length")
    if velocities.size < 2:
        raise ValueError("at least two RV epochs are required")
    if not np.all(np.isfinite(velocities)):
        raise ValueError("velocities must all be finite")
    if not np.all(np.isfinite(errors)) or np.any(errors <= 0):
        raise ValueError("errors must all be finite and positive")

    best = 0.0
    for i in range(velocities.size - 1):
        delta = np.abs(velocities[i + 1 :] - velocities[i])
        sigma = np.sqrt(errors[i + 1 :] ** 2 + errors[i] ** 2)
        best = max(best, float(np.max(delta / sigma)))
    return best
