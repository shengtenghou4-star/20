"""Roche-lobe geometry checks for HOU-COMPACT contaminant rejection.

A published spectroscopic orbit and a single-star radius estimate can be mutually
inconsistent even before an unseen-companion interpretation is considered.  These
routines propagate broad quantile summaries into a conservative primary Roche-lobe
filling-factor posterior.  They are a veto/diagnostic, never a compact-object label.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass

import numpy as np

_G_SI = 6.67430e-11
_M_SUN_KG = 1.98847e30
_R_SUN_M = 6.957e8
_DAY_S = 86400.0
_Q16_NORMAL = 0.994457883209753


def orbital_separation_solar_radii(
    period_days: float | np.ndarray,
    primary_mass_solar: float | np.ndarray,
    companion_mass_solar: float | np.ndarray,
) -> np.ndarray:
    """Return Keplerian semi-major axis in solar radii."""
    period = np.asarray(period_days, dtype=float)
    primary = np.asarray(primary_mass_solar, dtype=float)
    companion = np.asarray(companion_mass_solar, dtype=float)
    if np.any(~np.isfinite(period)) or np.any(period <= 0):
        raise ValueError("period_days must be finite and positive")
    if np.any(~np.isfinite(primary)) or np.any(primary <= 0):
        raise ValueError("primary_mass_solar must be finite and positive")
    if np.any(~np.isfinite(companion)) or np.any(companion <= 0):
        raise ValueError("companion_mass_solar must be finite and positive")
    period_seconds = period * _DAY_S
    total_mass_kg = (primary + companion) * _M_SUN_KG
    separation_m = (
        _G_SI * total_mass_kg * period_seconds**2 / (4.0 * math.pi**2)
    ) ** (1.0 / 3.0)
    return separation_m / _R_SUN_M


def eggleton_primary_roche_fraction(mass_ratio_primary_to_companion: float | np.ndarray) -> np.ndarray:
    """Return the primary Roche-lobe radius divided by instantaneous separation."""
    ratio = np.asarray(mass_ratio_primary_to_companion, dtype=float)
    if np.any(~np.isfinite(ratio)) or np.any(ratio <= 0):
        raise ValueError("mass ratio must be finite and positive")
    q13 = np.cbrt(ratio)
    q23 = q13**2
    return 0.49 * q23 / (0.6 * q23 + np.log1p(q13))


def primary_roche_lobe_radius_solar(
    period_days: float | np.ndarray,
    eccentricity: float | np.ndarray,
    primary_mass_solar: float | np.ndarray,
    companion_mass_solar: float | np.ndarray,
) -> np.ndarray:
    """Return the primary Roche-lobe radius at periastron in solar radii."""
    eccentricity_array = np.asarray(eccentricity, dtype=float)
    if np.any(~np.isfinite(eccentricity_array)) or np.any(
        (eccentricity_array < 0) | (eccentricity_array >= 1)
    ):
        raise ValueError("eccentricity must be finite and in [0, 1)")
    primary = np.asarray(primary_mass_solar, dtype=float)
    companion = np.asarray(companion_mass_solar, dtype=float)
    semi_major_axis = orbital_separation_solar_radii(
        period_days,
        primary,
        companion,
    )
    periastron_separation = semi_major_axis * (1.0 - eccentricity_array)
    fraction = eggleton_primary_roche_fraction(primary / companion)
    return periastron_separation * fraction


def deterministic_roche_seed(source_id: int, solution_id: int, base_seed: int = 20260722) -> int:
    """Return a stable 32-bit seed without exposing source identity in outputs."""
    payload = f"{base_seed}:{int(source_id)}:{int(solution_id)}:roche".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def _split_normal_draws(
    rng: np.random.Generator,
    lower: float,
    median: float,
    upper: float,
    size: int,
    *,
    positive: bool = True,
) -> np.ndarray:
    values = np.asarray([lower, median, upper], dtype=float)
    if np.any(~np.isfinite(values)) or not lower <= median <= upper:
        raise ValueError("quantiles must be finite and ordered")
    lower_sigma = max((median - lower) / _Q16_NORMAL, abs(median) * 1e-6, 1e-9)
    upper_sigma = max((upper - median) / _Q16_NORMAL, abs(median) * 1e-6, 1e-9)
    standard = rng.standard_normal(size)
    draws = median + np.where(standard < 0, lower_sigma, upper_sigma) * standard
    if positive:
        draws = draws[draws > 0]
    return draws


@dataclass(frozen=True)
class RocheGeometryPosterior:
    """Candidate-safe summary of a primary Roche filling-factor posterior."""

    status: str
    n_draws_requested: int
    n_draws_accepted: int
    acceptance_fraction: float
    filling_q01: float
    filling_q05: float
    filling_q16: float
    filling_q50: float
    filling_q84: float
    filling_q95: float
    filling_q99: float
    probability_filling_gt_0p8: float
    probability_filling_gt_1p0: float
    periastron_roche_radius_q16_solar: float
    periastron_roche_radius_q50_solar: float
    periastron_roche_radius_q84_solar: float
    interpretation: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def infer_roche_geometry_posterior(
    *,
    period_days: float,
    period_error_days: float,
    eccentricity: float,
    eccentricity_error: float,
    primary_mass_q16_solar: float,
    primary_mass_q50_solar: float,
    primary_mass_q84_solar: float,
    companion_mass_q16_solar: float,
    companion_mass_q50_solar: float,
    companion_mass_q84_solar: float,
    primary_radius_q16_solar: float,
    primary_radius_q50_solar: float,
    primary_radius_q84_solar: float,
    n_draws: int = 20_000,
    random_seed: int = 20260722,
) -> RocheGeometryPosterior:
    """Propagate broad orbit/mass/radius uncertainties into Roche filling factor.

    The primary and companion mass summaries are sampled independently from their
    q16/q50/q84 approximations.  This deliberately broad audit is not a replacement for
    a joint evolutionary-orbital posterior; its role is to expose geometrically
    impossible or near-contact single-star interpretations.
    """
    if n_draws < 100:
        raise ValueError("n_draws must be at least 100")
    scalars = {
        "period_days": period_days,
        "period_error_days": period_error_days,
        "eccentricity": eccentricity,
        "eccentricity_error": eccentricity_error,
    }
    for name, value in scalars.items():
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if period_days <= 0 or period_error_days < 0:
        raise ValueError("period and period uncertainty are invalid")
    if not 0 <= eccentricity < 1 or eccentricity_error < 0:
        raise ValueError("eccentricity and uncertainty are invalid")

    rng = np.random.default_rng(random_seed)
    primary = _split_normal_draws(
        rng,
        primary_mass_q16_solar,
        primary_mass_q50_solar,
        primary_mass_q84_solar,
        n_draws,
    )
    companion = _split_normal_draws(
        rng,
        companion_mass_q16_solar,
        companion_mass_q50_solar,
        companion_mass_q84_solar,
        n_draws,
    )
    radius = _split_normal_draws(
        rng,
        primary_radius_q16_solar,
        primary_radius_q50_solar,
        primary_radius_q84_solar,
        n_draws,
    )
    period_sigma = max(period_error_days, period_days * 1e-8)
    period = rng.normal(period_days, period_sigma, n_draws)
    eccentricity_draws = rng.normal(
        eccentricity,
        max(eccentricity_error, 1e-8),
        n_draws,
    )

    accepted = min(len(primary), len(companion), len(radius), len(period))
    primary = primary[:accepted]
    companion = companion[:accepted]
    radius = radius[:accepted]
    period = period[:accepted]
    eccentricity_draws = eccentricity_draws[:accepted]
    valid = (
        np.isfinite(primary)
        & np.isfinite(companion)
        & np.isfinite(radius)
        & np.isfinite(period)
        & np.isfinite(eccentricity_draws)
        & (primary > 0)
        & (companion > 0)
        & (radius > 0)
        & (period > 0)
        & (eccentricity_draws >= 0)
        & (eccentricity_draws < 0.95)
    )
    primary = primary[valid]
    companion = companion[valid]
    radius = radius[valid]
    period = period[valid]
    eccentricity_draws = eccentricity_draws[valid]
    if len(primary) < max(100, int(0.25 * n_draws)):
        raise ValueError("too few physical Roche-geometry draws survived")

    roche_radius = primary_roche_lobe_radius_solar(
        period,
        eccentricity_draws,
        primary,
        companion,
    )
    filling = radius / roche_radius
    quantiles = np.quantile(filling, [0.01, 0.05, 0.16, 0.5, 0.84, 0.95, 0.99])
    roche_quantiles = np.quantile(roche_radius, [0.16, 0.5, 0.84])
    probability_gt_08 = float(np.mean(filling > 0.8))
    probability_gt_10 = float(np.mean(filling > 1.0))
    if float(quantiles[2]) > 1.0 or probability_gt_10 >= 0.95:
        status = "geometry_inconsistent"
    elif float(quantiles[3]) > 0.8 or probability_gt_08 >= 0.5:
        status = "near_or_overflowing_roche_lobe"
    else:
        status = "detached_geometry_consistent"

    return RocheGeometryPosterior(
        status=status,
        n_draws_requested=n_draws,
        n_draws_accepted=len(filling),
        acceptance_fraction=len(filling) / n_draws,
        filling_q01=float(quantiles[0]),
        filling_q05=float(quantiles[1]),
        filling_q16=float(quantiles[2]),
        filling_q50=float(quantiles[3]),
        filling_q84=float(quantiles[4]),
        filling_q95=float(quantiles[5]),
        filling_q99=float(quantiles[6]),
        probability_filling_gt_0p8=probability_gt_08,
        probability_filling_gt_1p0=probability_gt_10,
        periastron_roche_radius_q16_solar=float(roche_quantiles[0]),
        periastron_roche_radius_q50_solar=float(roche_quantiles[1]),
        periastron_roche_radius_q84_solar=float(roche_quantiles[2]),
        interpretation=(
            "Roche geometry uses Gaia single-star radius summaries and approximate "
            "quantile sampling. Inconsistency challenges the adopted orbit/stellar model; "
            "consistency does not establish a dark companion."
        ),
    )
