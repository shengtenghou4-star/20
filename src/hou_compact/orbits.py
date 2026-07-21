"""Keplerian radial-velocity models for independent Gaia/DESI consistency tests."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from astropy.time import Time

_TWO_PI = 2.0 * math.pi


def gaia_reference_epoch_mjd(ref_epoch_jyear: float) -> float:
    """Convert a Gaia Julian-year reference epoch in TCB to UTC MJD."""
    if not math.isfinite(ref_epoch_jyear):
        raise ValueError("ref_epoch_jyear must be finite")
    return float(Time(ref_epoch_jyear, format="jyear", scale="tcb").utc.mjd)


def gaia_periastron_mjd(ref_epoch_jyear: float, t_periastron_days: float) -> float:
    """Return the absolute UTC MJD of Gaia's relative periastron epoch."""
    if not math.isfinite(t_periastron_days):
        raise ValueError("t_periastron_days must be finite")
    return gaia_reference_epoch_mjd(ref_epoch_jyear) + t_periastron_days


def solve_kepler(
    mean_anomaly_rad: float | Sequence[float] | np.ndarray,
    eccentricity: float,
    *,
    tolerance: float = 1e-13,
    max_iterations: int = 100,
) -> np.ndarray:
    """Solve ``E - e sin(E) = M`` by monotonic vectorized bisection.

    For ``0 <= e < 1`` the left-hand side is strictly increasing, so the wrapped
    solution is uniquely bracketed by ``[-pi, pi]``. Bisection is slightly slower than
    unrestricted Newton iteration but cannot diverge for high-eccentricity systems.
    """
    if not math.isfinite(eccentricity) or not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must be finite and satisfy 0 <= e < 1")
    if tolerance <= 0 or not math.isfinite(tolerance):
        raise ValueError("tolerance must be finite and positive")
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")

    mean = np.asarray(mean_anomaly_rad, dtype=float)
    if not np.all(np.isfinite(mean)):
        raise ValueError("mean anomaly values must be finite")
    wrapped = (mean + math.pi) % _TWO_PI - math.pi
    positive_pi_boundary = np.isclose(wrapped, -math.pi, atol=1e-15) & (mean > 0)
    wrapped = np.where(positive_pi_boundary, math.pi, wrapped)
    low = np.full_like(wrapped, -math.pi, dtype=float)
    high = np.full_like(wrapped, math.pi, dtype=float)

    for _ in range(max_iterations):
        midpoint = 0.5 * (low + high)
        residual = midpoint - eccentricity * np.sin(midpoint) - wrapped
        high = np.where(residual > 0.0, midpoint, high)
        low = np.where(residual > 0.0, low, midpoint)
        if np.max(high - low, initial=0.0) <= 2.0 * tolerance:
            return 0.5 * (low + high)
    raise RuntimeError("Kepler solver did not converge within the requested tolerance")


def true_anomaly_from_eccentric_anomaly(
    eccentric_anomaly_rad: float | Sequence[float] | np.ndarray,
    eccentricity: float,
) -> np.ndarray:
    """Convert eccentric anomaly to true anomaly with a quadrant-safe formula."""
    if not math.isfinite(eccentricity) or not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must be finite and satisfy 0 <= e < 1")
    eccentric = np.asarray(eccentric_anomaly_rad, dtype=float)
    if not np.all(np.isfinite(eccentric)):
        raise ValueError("eccentric anomaly values must be finite")
    numerator = np.sqrt(1.0 - eccentricity**2) * np.sin(eccentric)
    denominator = np.cos(eccentric) - eccentricity
    return np.arctan2(numerator, denominator)


def sb1_velocity_shape(
    mjd: float | Sequence[float] | np.ndarray,
    *,
    period_days: float,
    periastron_mjd: float,
    eccentricity: float,
    arg_periastron_deg: float,
    semi_amplitude_kms: float,
) -> np.ndarray:
    """Return the zero-systemic-velocity SB1 Keplerian RV curve in km/s."""
    for name, value in (
        ("period_days", period_days),
        ("periastron_mjd", periastron_mjd),
        ("arg_periastron_deg", arg_periastron_deg),
        ("semi_amplitude_kms", semi_amplitude_kms),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if period_days <= 0:
        raise ValueError("period_days must be positive")
    if semi_amplitude_kms <= 0:
        raise ValueError("semi_amplitude_kms must be positive")
    if not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must satisfy 0 <= e < 1")

    times = np.asarray(mjd, dtype=float)
    if not np.all(np.isfinite(times)):
        raise ValueError("mjd values must be finite")
    mean_anomaly = _TWO_PI * (times - periastron_mjd) / period_days
    eccentric_anomaly = solve_kepler(mean_anomaly, eccentricity)
    true_anomaly = true_anomaly_from_eccentric_anomaly(eccentric_anomaly, eccentricity)
    omega = math.radians(arg_periastron_deg)
    return semi_amplitude_kms * (
        np.cos(true_anomaly + omega) + eccentricity * math.cos(omega)
    )


def gaia_sb1_velocity_shape(
    mjd: float | Sequence[float] | np.ndarray,
    *,
    ref_epoch_jyear: float,
    period_days: float,
    t_periastron_days: float,
    eccentricity: float | None,
    arg_periastron_deg: float | None,
    semi_amplitude_kms: float,
) -> np.ndarray:
    """Evaluate a Gaia SB1/SB1C curve, normalizing circular-solution nulls.

    Gaia SB1C solutions leave eccentricity and argument of periastron null. Gaia's
    circular-orbit convention places the relative epoch at maximum RV, equivalent to
    setting ``e=0`` and ``omega=0`` in the standard SB1 equation.
    """
    normalized_e = (
        0.0 if eccentricity is None or not math.isfinite(eccentricity) else eccentricity
    )
    normalized_omega = (
        0.0
        if arg_periastron_deg is None or not math.isfinite(arg_periastron_deg)
        else arg_periastron_deg
    )
    return sb1_velocity_shape(
        mjd,
        period_days=period_days,
        periastron_mjd=gaia_periastron_mjd(ref_epoch_jyear, t_periastron_days),
        eccentricity=normalized_e,
        arg_periastron_deg=normalized_omega,
        semi_amplitude_kms=semi_amplitude_kms,
    )


@dataclass(frozen=True)
class OrbitConsistency:
    systemic_velocity_kms: float
    chi2: float
    degrees_of_freedom: int
    reduced_chi2: float
    residuals_kms: np.ndarray


def fit_systemic_velocity(
    observed_velocity_kms: Sequence[float] | np.ndarray,
    observed_error_kms: Sequence[float] | np.ndarray,
    velocity_shape_kms: Sequence[float] | np.ndarray,
    *,
    jitter_kms: float = 0.0,
) -> OrbitConsistency:
    """Fit one cross-survey RV zero point and score a fixed Gaia orbit shape.

    Only an additive systemic velocity is fitted. Period, phase, eccentricity, omega,
    and K1 remain fixed, so this is an independent shape/phase test rather than a
    re-fit that can absorb arbitrary discrepancies.
    """
    observed = np.asarray(observed_velocity_kms, dtype=float)
    errors = np.asarray(observed_error_kms, dtype=float)
    shape = np.asarray(velocity_shape_kms, dtype=float)
    if observed.ndim != 1 or errors.ndim != 1 or shape.ndim != 1:
        raise ValueError("observed, errors, and shape must be one-dimensional")
    if not (observed.size == errors.size == shape.size):
        raise ValueError("observed, errors, and shape must have equal lengths")
    if observed.size < 2:
        raise ValueError("at least two epochs are required")
    if not np.all(np.isfinite(observed)) or not np.all(np.isfinite(shape)):
        raise ValueError("observed velocities and model shape must be finite")
    if not np.all(np.isfinite(errors)) or np.any(errors <= 0):
        raise ValueError("errors must be finite and positive")
    if not math.isfinite(jitter_kms) or jitter_kms < 0:
        raise ValueError("jitter_kms must be finite and non-negative")

    variance = errors**2 + jitter_kms**2
    weights = 1.0 / variance
    gamma = float(np.sum(weights * (observed - shape)) / np.sum(weights))
    residuals = observed - (gamma + shape)
    chi2 = float(np.sum(residuals**2 / variance))
    dof = int(observed.size - 1)
    return OrbitConsistency(
        systemic_velocity_kms=gamma,
        chi2=chi2,
        degrees_of_freedom=dof,
        reduced_chi2=chi2 / dof,
        residuals_kms=residuals,
    )
