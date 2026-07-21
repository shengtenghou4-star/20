"""Preliminary primary-star mass proxies from Gaia GSP-Phot gravity and radius.

GSP-Phot parameters are inferred under a single-star assumption. Products from this
module are triage priors only and must be replaced or validated with independent stellar
characterization before any compact-object claim.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

LOGG_SUN_CGS = 4.438
_QUANTILES = (0.01, 0.05, 0.16, 0.5, 0.84, 0.95, 0.99)


@dataclass(frozen=True)
class PrimaryMassSamples:
    """Monte Carlo samples for the GSP-Phot gravity-radius mass proxy."""

    mass_solar: np.ndarray
    logg_cgs: np.ndarray
    radius_solar: np.ndarray
    random_seed: int


def mass_from_logg_radius(
    logg_cgs: float | np.ndarray,
    radius_solar: float | np.ndarray,
) -> np.ndarray:
    """Return M/Msun = 10^(logg-logg_sun) * (R/Rsun)^2."""
    logg = np.asarray(logg_cgs, dtype=float)
    radius = np.asarray(radius_solar, dtype=float)
    if np.any(~np.isfinite(logg)):
        raise ValueError("logg values must be finite")
    if np.any(~np.isfinite(radius)) or np.any(radius <= 0):
        raise ValueError("radius values must be finite and positive")
    return np.power(10.0, logg - LOGG_SUN_CGS) * radius**2


def _validate_quantile_triplet(
    lower: float,
    median: float,
    upper: float,
    *,
    name: str,
) -> None:
    if not all(math.isfinite(value) for value in (lower, median, upper)):
        raise ValueError(f"{name} quantiles must be finite")
    if not lower <= median <= upper:
        raise ValueError(f"{name} quantiles must satisfy lower <= median <= upper")


def _draw_split_normal_from_16_50_84(
    rng: np.random.Generator,
    lower: float,
    median: float,
    upper: float,
    size: int,
    *,
    name: str,
    minimum: float | None = None,
) -> np.ndarray:
    """Approximate asymmetric 16/50/84 percentiles with a two-piece Gaussian."""
    _validate_quantile_triplet(lower, median, upper, name=name)
    z16 = abs(float(norm.ppf(0.16)))
    z84 = float(norm.ppf(0.84))
    sigma_lower = (median - lower) / z16 if median > lower else 0.0
    sigma_upper = (upper - median) / z84 if upper > median else 0.0
    if sigma_lower == 0.0 and sigma_upper == 0.0:
        samples = np.full(size, median, dtype=float)
    else:
        uniforms = rng.uniform(np.finfo(float).eps, 1.0 - np.finfo(float).eps, size=size)
        z = norm.ppf(uniforms)
        scale = np.where(z < 0, sigma_lower, sigma_upper)
        samples = median + z * scale

    if minimum is None:
        return np.asarray(samples, dtype=float)
    if not math.isfinite(minimum):
        raise ValueError("minimum must be finite")
    invalid = samples <= minimum
    for _ in range(40):
        count = int(np.sum(invalid))
        if count == 0:
            return np.asarray(samples, dtype=float)
        uniforms = rng.uniform(
            np.finfo(float).eps,
            1.0 - np.finfo(float).eps,
            size=count,
        )
        z = norm.ppf(uniforms)
        scale = np.where(z < 0, sigma_lower, sigma_upper)
        samples[invalid] = median + z * scale
        invalid = samples <= minimum
    raise RuntimeError(f"failed to draw positive {name} samples")


def draw_gspphot_primary_mass(
    *,
    logg_median: float,
    logg_lower: float,
    logg_upper: float,
    radius_median: float,
    radius_lower: float,
    radius_upper: float,
    n_draws: int = 50_000,
    random_seed: int = 0,
) -> PrimaryMassSamples:
    """Draw a diagonal GSP-Phot gravity-radius mass proxy distribution."""
    if not isinstance(n_draws, int) or n_draws < 100:
        raise ValueError("n_draws must be an integer of at least 100")
    if not isinstance(random_seed, int) or random_seed < 0:
        raise ValueError("random_seed must be a non-negative integer")
    rng = np.random.default_rng(random_seed)
    logg = _draw_split_normal_from_16_50_84(
        rng,
        logg_lower,
        logg_median,
        logg_upper,
        n_draws,
        name="logg_gspphot",
    )
    radius = _draw_split_normal_from_16_50_84(
        rng,
        radius_lower,
        radius_median,
        radius_upper,
        n_draws,
        name="radius_gspphot",
        minimum=0.0,
    )
    mass = mass_from_logg_radius(logg, radius)
    return PrimaryMassSamples(
        mass_solar=mass,
        logg_cgs=logg,
        radius_solar=radius,
        random_seed=random_seed,
    )


def summarize_primary_mass(samples: PrimaryMassSamples) -> dict[str, object]:
    """Return robust quantiles and a symmetric adapter error for downstream pilots."""
    if samples.mass_solar.size == 0:
        raise ValueError("primary-mass samples are empty")
    mass_quantiles = np.quantile(samples.mass_solar, _QUANTILES)
    logg_quantiles = np.quantile(samples.logg_cgs, _QUANTILES)
    radius_quantiles = np.quantile(samples.radius_solar, _QUANTILES)
    q16 = float(mass_quantiles[2])
    q50 = float(mass_quantiles[3])
    q84 = float(mass_quantiles[4])
    return {
        "n_draws": int(samples.mass_solar.size),
        "random_seed": samples.random_seed,
        "quantiles": list(_QUANTILES),
        "mass_quantiles_solar": [float(value) for value in mass_quantiles],
        "logg_quantiles_cgs": [float(value) for value in logg_quantiles],
        "radius_quantiles_solar": [float(value) for value in radius_quantiles],
        "primary_mass_solar": q50,
        "primary_mass_error_solar": 0.5 * (q84 - q16),
        "primary_mass_lower_solar": q16,
        "primary_mass_upper_solar": q84,
        "fractional_68_width": (q84 - q16) / (2.0 * q50),
        "method": "gaia_gspphot_logg_radius_diagonal_proxy",
        "interpretation": (
            "triage-only single-star-assumption proxy; independent validation required"
        ),
    }
