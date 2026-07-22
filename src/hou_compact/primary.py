"""Preliminary primary-star mass priors from Gaia GSP-Phot and FLAME.

Gaia astrophysical parameters are inferred under single-star assumptions. Products from
this module are triage priors only and must be replaced or validated with independent
stellar characterization before any compact-object claim.
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


@dataclass(frozen=True)
class FlamePrimaryMassSamples:
    """Monte Carlo samples reconstructed from Gaia FLAME mass percentiles."""

    mass_solar: np.ndarray
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


def _validate_draw_settings(n_draws: int, random_seed: int) -> None:
    if not isinstance(n_draws, int) or n_draws < 100:
        raise ValueError("n_draws must be an integer of at least 100")
    if not isinstance(random_seed, int) or random_seed < 0:
        raise ValueError("random_seed must be a non-negative integer")


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
    _validate_draw_settings(n_draws, random_seed)
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


def draw_flame_primary_mass(
    *,
    mass_median: float,
    mass_lower: float,
    mass_upper: float,
    n_draws: int = 50_000,
    random_seed: int = 0,
) -> FlamePrimaryMassSamples:
    """Draw a positive mass prior from Gaia FLAME 16/50/84 percentiles."""
    _validate_draw_settings(n_draws, random_seed)
    rng = np.random.default_rng(random_seed)
    mass = _draw_split_normal_from_16_50_84(
        rng,
        mass_lower,
        mass_median,
        mass_upper,
        n_draws,
        name="mass_flame",
        minimum=0.0,
    )
    return FlamePrimaryMassSamples(mass_solar=mass, random_seed=random_seed)


def _mass_summary(
    mass_solar: np.ndarray,
    *,
    random_seed: int,
    method: str,
    interpretation: str,
) -> dict[str, object]:
    if mass_solar.size == 0:
        raise ValueError("primary-mass samples are empty")
    if np.any(~np.isfinite(mass_solar)) or np.any(mass_solar <= 0):
        raise ValueError("primary-mass samples must be finite and positive")
    mass_quantiles = np.quantile(mass_solar, _QUANTILES)
    q16 = float(mass_quantiles[2])
    q50 = float(mass_quantiles[3])
    q84 = float(mass_quantiles[4])
    return {
        "n_draws": int(mass_solar.size),
        "random_seed": random_seed,
        "quantiles": list(_QUANTILES),
        "mass_quantiles_solar": [float(value) for value in mass_quantiles],
        "primary_mass_solar": q50,
        "primary_mass_error_solar": 0.5 * (q84 - q16),
        "primary_mass_lower_solar": q16,
        "primary_mass_upper_solar": q84,
        "fractional_68_width": (q84 - q16) / (2.0 * q50),
        "method": method,
        "interpretation": interpretation,
    }


def summarize_primary_mass(samples: PrimaryMassSamples) -> dict[str, object]:
    """Return robust quantiles and a symmetric adapter error for GSP-Phot samples."""
    summary = _mass_summary(
        samples.mass_solar,
        random_seed=samples.random_seed,
        method="gaia_gspphot_logg_radius_diagonal_proxy",
        interpretation=(
            "triage-only GSP-Phot single-star-assumption proxy; independent validation required"
        ),
    )
    summary["logg_quantiles_cgs"] = [
        float(value) for value in np.quantile(samples.logg_cgs, _QUANTILES)
    ]
    summary["radius_quantiles_solar"] = [
        float(value) for value in np.quantile(samples.radius_solar, _QUANTILES)
    ]
    return summary


def summarize_flame_primary_mass(
    samples: FlamePrimaryMassSamples,
) -> dict[str, object]:
    """Return robust quantiles for a Gaia FLAME primary-mass prior."""
    return _mass_summary(
        samples.mass_solar,
        random_seed=samples.random_seed,
        method="gaia_flame_mass_percentile_prior",
        interpretation=(
            "triage-only FLAME stellar-model prior under single-star assumptions; "
            "independent validation required"
        ),
    )
