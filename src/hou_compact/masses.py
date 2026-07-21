"""Monte Carlo mass-function products for single-lined spectroscopic binaries.

The robust product is the edge-on minimum-companion-mass distribution. An isotropic
inclination product is also provided as an explicitly labelled geometry-only sensitivity
analysis; it is not a selection-function-corrected population posterior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import truncnorm

_G_SI = 6.67430e-11
_M_SUN_KG = 1.98847e30
_DAY_S = 86400.0
_KM_S_TO_M_S = 1000.0
_DEFAULT_QUANTILES = (0.01, 0.05, 0.16, 0.5, 0.84, 0.95, 0.99)
_DEFAULT_THRESHOLDS_SOLAR = (1.4, 2.5, 3.0, 5.0, 10.0)


@dataclass(frozen=True)
class MassPosteriorSamples:
    """Accepted Monte Carlo samples for one SB1 mass product."""

    mass_function_solar: np.ndarray
    companion_mass_solar: np.ndarray
    primary_mass_solar: np.ndarray
    sin_inclination: np.ndarray
    inclination_mode: str
    random_seed: int


def _validate_location_scale(name: str, location: float, scale: float) -> None:
    if not math.isfinite(location):
        raise ValueError(f"{name} location must be finite")
    if not math.isfinite(scale) or scale < 0:
        raise ValueError(f"{name} scale must be finite and non-negative")


def _sample_truncated_normal(
    rng: np.random.Generator,
    location: float,
    scale: float,
    size: int,
    *,
    low: float,
    high: float,
    name: str,
) -> np.ndarray:
    _validate_location_scale(name, location, scale)
    if not math.isfinite(low) or not math.isfinite(high) or not low < high:
        raise ValueError(f"invalid truncation interval for {name}")
    if not low <= location <= high:
        raise ValueError(f"{name} location lies outside truncation interval")
    if scale == 0:
        return np.full(size, location, dtype=float)
    a = (low - location) / scale
    b = (high - location) / scale
    return np.asarray(
        truncnorm.rvs(a, b, loc=location, scale=scale, size=size, random_state=rng),
        dtype=float,
    )


def _sample_sin_inclination(
    rng: np.random.Generator,
    size: int,
    *,
    mode: str,
    inclination_deg: float | None,
    inclination_error_deg: float | None,
    minimum_inclination_deg: float,
) -> np.ndarray:
    if not math.isfinite(minimum_inclination_deg) or not 0 <= minimum_inclination_deg < 90:
        raise ValueError("minimum_inclination_deg must be in [0, 90)")
    mode_normalized = mode.lower().replace("-", "_")
    if mode_normalized == "edge_on":
        return np.ones(size, dtype=float)
    if mode_normalized == "isotropic":
        maximum_cosine = math.cos(math.radians(minimum_inclination_deg))
        cosine = rng.uniform(0.0, maximum_cosine, size=size)
        return np.sqrt(np.maximum(0.0, 1.0 - cosine**2))
    if mode_normalized == "fixed":
        if inclination_deg is None or not math.isfinite(inclination_deg):
            raise ValueError("inclination_deg is required for fixed mode")
        if not minimum_inclination_deg <= inclination_deg <= 90:
            raise ValueError("fixed inclination lies outside allowed interval")
        return np.full(size, math.sin(math.radians(inclination_deg)), dtype=float)
    if mode_normalized == "normal":
        if inclination_deg is None or inclination_error_deg is None:
            raise ValueError("inclination_deg and inclination_error_deg are required")
        inclination = _sample_truncated_normal(
            rng,
            inclination_deg,
            inclination_error_deg,
            size,
            low=minimum_inclination_deg,
            high=90.0,
            name="inclination_deg",
        )
        return np.sin(np.radians(inclination))
    raise ValueError(f"unsupported inclination mode: {mode!r}")


def _spectroscopic_mass_function_vectorized(
    period_days: np.ndarray,
    k1_kms: np.ndarray,
    eccentricity: np.ndarray,
) -> np.ndarray:
    period_s = period_days * _DAY_S
    k1_ms = k1_kms * _KM_S_TO_M_S
    return (
        period_s
        * k1_ms**3
        * np.power(1.0 - eccentricity**2, 1.5)
        / (2.0 * math.pi * _G_SI)
        / _M_SUN_KG
    )


def _solve_companion_mass_vectorized(
    primary_mass_solar: np.ndarray,
    mass_function_solar: np.ndarray,
    sin_inclination: np.ndarray,
    *,
    relative_tolerance: float = 1e-10,
    max_iterations: int = 160,
) -> np.ndarray:
    """Solve the SB1 mass-function equation by vectorized monotonic bisection."""
    primary = np.asarray(primary_mass_solar, dtype=float)
    mass_function = np.asarray(mass_function_solar, dtype=float)
    sine = np.asarray(sin_inclination, dtype=float)
    if not (primary.shape == mass_function.shape == sine.shape):
        raise ValueError("primary mass, mass function, and inclination arrays must align")
    if np.any(~np.isfinite(primary)) or np.any(primary <= 0):
        raise ValueError("primary-mass samples must be finite and positive")
    if np.any(~np.isfinite(mass_function)) or np.any(mass_function <= 0):
        raise ValueError("mass-function samples must be finite and positive")
    if np.any(~np.isfinite(sine)) or np.any((sine <= 0) | (sine > 1)):
        raise ValueError("sin-inclination samples must be in (0, 1]")
    if not math.isfinite(relative_tolerance) or relative_tolerance <= 0:
        raise ValueError("relative_tolerance must be finite and positive")
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")

    sine_cubed = sine**3

    def residual(mass: np.ndarray) -> np.ndarray:
        return mass**3 * sine_cubed / (primary + mass) ** 2 - mass_function

    low = np.zeros_like(primary)
    high = np.maximum.reduce(
        [
            np.ones_like(primary),
            primary,
            mass_function / sine_cubed,
        ]
    )
    for _ in range(80):
        unresolved = residual(high) < 0
        if not np.any(unresolved):
            break
        high[unresolved] *= 2.0
        if np.any(high > 1e8):
            raise RuntimeError("failed to bracket one or more companion-mass roots")
    else:
        raise RuntimeError("companion-mass bracketing did not converge")

    for _ in range(max_iterations):
        midpoint = 0.5 * (low + high)
        positive = residual(midpoint) > 0
        high = np.where(positive, midpoint, high)
        low = np.where(positive, low, midpoint)
        width = high - low
        if np.all(width <= relative_tolerance * np.maximum(1.0, midpoint)):
            return 0.5 * (low + high)
    raise RuntimeError("companion-mass bisection did not converge")


def draw_mass_posterior(
    *,
    period_days: float,
    period_error_days: float,
    k1_kms: float,
    k1_error_kms: float,
    eccentricity: float,
    eccentricity_error: float,
    primary_mass_solar: float,
    primary_mass_error_solar: float,
    n_draws: int = 50_000,
    inclination_mode: str = "edge_on",
    inclination_deg: float | None = None,
    inclination_error_deg: float | None = None,
    minimum_inclination_deg: float = 0.0,
    random_seed: int = 0,
) -> MassPosteriorSamples:
    """Draw a diagonal-error SB1 mass posterior.

    Orbital parameter correlations are not used by this function. Callers must label
    this as a diagonal approximation until Gaia's ``corr_vec`` is decoded and applied.
    """
    if not isinstance(n_draws, int) or n_draws < 100:
        raise ValueError("n_draws must be an integer of at least 100")
    if not isinstance(random_seed, int) or random_seed < 0:
        raise ValueError("random_seed must be a non-negative integer")
    rng = np.random.default_rng(random_seed)

    period = _sample_truncated_normal(
        rng,
        period_days,
        period_error_days,
        n_draws,
        low=np.finfo(float).tiny,
        high=max(period_days + 20.0 * max(period_error_days, 1.0), period_days * 100.0),
        name="period_days",
    )
    k1 = _sample_truncated_normal(
        rng,
        k1_kms,
        k1_error_kms,
        n_draws,
        low=np.finfo(float).tiny,
        high=max(k1_kms + 20.0 * max(k1_error_kms, 1.0), k1_kms * 100.0),
        name="k1_kms",
    )
    eccentricity_samples = _sample_truncated_normal(
        rng,
        eccentricity,
        eccentricity_error,
        n_draws,
        low=0.0,
        high=np.nextafter(1.0, 0.0),
        name="eccentricity",
    )
    primary_mass = _sample_truncated_normal(
        rng,
        primary_mass_solar,
        primary_mass_error_solar,
        n_draws,
        low=np.finfo(float).tiny,
        high=max(
            primary_mass_solar + 20.0 * max(primary_mass_error_solar, 0.1),
            primary_mass_solar * 20.0,
        ),
        name="primary_mass_solar",
    )
    sin_inclination = _sample_sin_inclination(
        rng,
        n_draws,
        mode=inclination_mode,
        inclination_deg=inclination_deg,
        inclination_error_deg=inclination_error_deg,
        minimum_inclination_deg=minimum_inclination_deg,
    )
    mass_function = _spectroscopic_mass_function_vectorized(period, k1, eccentricity_samples)
    companion_mass = _solve_companion_mass_vectorized(
        primary_mass,
        mass_function,
        sin_inclination,
    )
    return MassPosteriorSamples(
        mass_function_solar=mass_function,
        companion_mass_solar=companion_mass,
        primary_mass_solar=primary_mass,
        sin_inclination=sin_inclination,
        inclination_mode=inclination_mode,
        random_seed=random_seed,
    )


def summarize_mass_posterior(
    samples: MassPosteriorSamples,
    *,
    quantiles: tuple[float, ...] = _DEFAULT_QUANTILES,
    thresholds_solar: tuple[float, ...] = _DEFAULT_THRESHOLDS_SOLAR,
) -> dict[str, object]:
    """Summarize samples without tail-sensitive means."""
    if not quantiles or any(not 0 < value < 1 for value in quantiles):
        raise ValueError("quantiles must lie strictly between zero and one")
    if any(not math.isfinite(value) or value <= 0 for value in thresholds_solar):
        raise ValueError("thresholds_solar must be finite and positive")
    mass = samples.companion_mass_solar
    mass_function = samples.mass_function_solar
    if mass.size == 0 or mass_function.size != mass.size:
        raise ValueError("posterior samples are empty or misaligned")

    mass_q = np.quantile(mass, quantiles)
    function_q = np.quantile(mass_function, quantiles)
    summary: dict[str, object] = {
        "inclination_mode": samples.inclination_mode,
        "random_seed": samples.random_seed,
        "n_draws": int(mass.size),
        "median_sin_inclination": float(np.median(samples.sin_inclination)),
        "quantiles": list(quantiles),
        "companion_mass_quantiles_solar": [float(value) for value in mass_q],
        "mass_function_quantiles_solar": [float(value) for value in function_q],
    }
    for threshold in thresholds_solar:
        label = str(threshold).replace(".", "p")
        summary[f"probability_m2_gt_{label}_solar"] = float(np.mean(mass > threshold))
    return summary


def draw_standard_sb1_products(
    *,
    period_days: float,
    period_error_days: float,
    k1_kms: float,
    k1_error_kms: float,
    eccentricity: float,
    eccentricity_error: float,
    primary_mass_solar: float,
    primary_mass_error_solar: float,
    n_draws: int = 50_000,
    minimum_isotropic_inclination_deg: float = 0.0,
    random_seed: int = 0,
) -> dict[str, dict[str, object]]:
    """Return robust edge-on and labelled isotropic-sensitivity summaries."""
    common = {
        "period_days": period_days,
        "period_error_days": period_error_days,
        "k1_kms": k1_kms,
        "k1_error_kms": k1_error_kms,
        "eccentricity": eccentricity,
        "eccentricity_error": eccentricity_error,
        "primary_mass_solar": primary_mass_solar,
        "primary_mass_error_solar": primary_mass_error_solar,
        "n_draws": n_draws,
    }
    edge_on = draw_mass_posterior(
        **common,
        inclination_mode="edge_on",
        random_seed=random_seed,
    )
    isotropic = draw_mass_posterior(
        **common,
        inclination_mode="isotropic",
        minimum_inclination_deg=minimum_isotropic_inclination_deg,
        random_seed=random_seed + 1,
    )
    return {
        "minimum_mass": {
            **summarize_mass_posterior(edge_on),
            "interpretation": "edge-on minimum-mass distribution with measurement uncertainty",
        },
        "isotropic_sensitivity": {
            **summarize_mass_posterior(isotropic),
            "minimum_inclination_deg": minimum_isotropic_inclination_deg,
            "interpretation": (
                "geometry-only isotropic inclination sensitivity; not corrected for "
                "SB1 detection or selection effects"
            ),
        },
    }
