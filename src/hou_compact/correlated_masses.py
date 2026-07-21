"""Correlation-aware Gaia SB1/SB1C mass-function Monte Carlo products."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from hou_compact.gaia_covariance import (
    MassParameterCovariance,
    sb1_mass_parameter_covariance,
)
from hou_compact.masses import (
    MassPosteriorSamples,
    _sample_sin_inclination,
    _sample_truncated_normal,
    _solve_companion_mass_vectorized,
    _spectroscopic_mass_function_vectorized,
    summarize_mass_posterior,
)


@dataclass(frozen=True)
class CorrelatedMassPosterior:
    """Mass samples plus the Gaia covariance block used to generate them."""

    samples: MassPosteriorSamples
    orbital_covariance: MassParameterCovariance
    acceptance_fraction: float


def _draw_physical_orbital_samples(
    rng: np.random.Generator,
    mean: np.ndarray,
    covariance: np.ndarray,
    n_draws: int,
    *,
    has_eccentricity: bool,
    max_batches: int = 200,
) -> tuple[np.ndarray, float]:
    """Draw a truncated multivariate normal by bounded rejection sampling."""
    mean = np.asarray(mean, dtype=float)
    covariance = np.asarray(covariance, dtype=float)
    if mean.ndim != 1:
        raise ValueError("orbital mean must be one-dimensional")
    if covariance.shape != (mean.size, mean.size):
        raise ValueError("orbital covariance shape does not match mean")
    if np.any(~np.isfinite(mean)) or np.any(~np.isfinite(covariance)):
        raise ValueError("orbital mean and covariance must be finite")
    if n_draws < 100:
        raise ValueError("n_draws must be at least 100")

    accepted: list[np.ndarray] = []
    retained_count = 0
    physically_valid_count = 0
    proposed_count = 0
    batch_size = max(1024, min(50_000, n_draws * 2))
    for _ in range(max_batches):
        proposals = rng.multivariate_normal(
            mean,
            covariance,
            size=batch_size,
            check_valid="raise",
            method="eigh",
        )
        proposed_count += batch_size
        valid = (proposals[:, 0] > 0) & (proposals[:, 1] > 0)
        if has_eccentricity:
            valid &= (proposals[:, 2] >= 0) & (proposals[:, 2] < 1)
        physically_valid_count += int(np.sum(valid))
        selected = proposals[valid]
        if selected.size:
            needed = n_draws - retained_count
            selected = selected[:needed]
            accepted.append(selected)
            retained_count += len(selected)
        if retained_count >= n_draws:
            combined = np.concatenate(accepted, axis=0)
            return combined, physically_valid_count / proposed_count
    raise RuntimeError(
        f"only retained {retained_count} of {n_draws} requested physical orbital draws"
    )


def draw_gaia_correlated_mass_posterior(
    *,
    solution_type: str,
    bit_index: object,
    corr_vec: object,
    period_days: float,
    period_error_days: float,
    k1_kms: float,
    k1_error_kms: float,
    eccentricity: float | None,
    eccentricity_error: float | None,
    primary_mass_solar: float,
    primary_mass_error_solar: float,
    n_draws: int = 50_000,
    inclination_mode: str = "edge_on",
    inclination_deg: float | None = None,
    inclination_error_deg: float | None = None,
    minimum_inclination_deg: float = 0.0,
    random_seed: int = 0,
) -> CorrelatedMassPosterior:
    """Draw a bit-index-validated, correlation-aware SB1 or SB1C mass posterior."""
    if not isinstance(random_seed, int) or random_seed < 0:
        raise ValueError("random_seed must be a non-negative integer")
    solution = solution_type.strip()
    covariance_product = sb1_mass_parameter_covariance(
        solution_type=solution,
        bit_index=bit_index,
        corr_vec=corr_vec,
        period_error=period_error_days,
        k1_error=k1_error_kms,
        eccentricity_error=eccentricity_error,
    )
    if solution == "SB1":
        if eccentricity is None or not math.isfinite(eccentricity):
            raise ValueError("SB1 eccentricity must be finite")
        mean = np.asarray([period_days, k1_kms, eccentricity], dtype=float)
        has_eccentricity = True
    elif solution == "SB1C":
        mean = np.asarray([period_days, k1_kms], dtype=float)
        has_eccentricity = False
    else:
        raise ValueError(f"unsupported Gaia solution type: {solution_type!r}")

    rng = np.random.default_rng(random_seed)
    orbit, acceptance_fraction = _draw_physical_orbital_samples(
        rng,
        mean,
        covariance_product.covariance,
        n_draws,
        has_eccentricity=has_eccentricity,
    )
    period = orbit[:, 0]
    k1 = orbit[:, 1]
    eccentricity_samples = orbit[:, 2] if has_eccentricity else np.zeros(n_draws)
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
    mass_function = _spectroscopic_mass_function_vectorized(
        period,
        k1,
        eccentricity_samples,
    )
    companion_mass = _solve_companion_mass_vectorized(
        primary_mass,
        mass_function,
        sin_inclination,
    )
    samples = MassPosteriorSamples(
        mass_function_solar=mass_function,
        companion_mass_solar=companion_mass,
        primary_mass_solar=primary_mass,
        sin_inclination=sin_inclination,
        inclination_mode=inclination_mode,
        random_seed=random_seed,
    )
    return CorrelatedMassPosterior(
        samples=samples,
        orbital_covariance=covariance_product,
        acceptance_fraction=acceptance_fraction,
    )


def draw_standard_gaia_correlated_products(
    *,
    solution_type: str,
    bit_index: object,
    corr_vec: object,
    period_days: float,
    period_error_days: float,
    k1_kms: float,
    k1_error_kms: float,
    eccentricity: float | None,
    eccentricity_error: float | None,
    primary_mass_solar: float,
    primary_mass_error_solar: float,
    n_draws: int = 50_000,
    minimum_isotropic_inclination_deg: float = 0.0,
    random_seed: int = 0,
) -> dict[str, dict[str, object]]:
    """Return edge-on and isotropic products using Gaia's validated sparse covariance."""
    common = {
        "solution_type": solution_type,
        "bit_index": bit_index,
        "corr_vec": corr_vec,
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
    edge_on = draw_gaia_correlated_mass_posterior(
        **common,
        inclination_mode="edge_on",
        random_seed=random_seed,
    )
    isotropic = draw_gaia_correlated_mass_posterior(
        **common,
        inclination_mode="isotropic",
        minimum_inclination_deg=minimum_isotropic_inclination_deg,
        random_seed=random_seed + 1,
    )

    def package(result: CorrelatedMassPosterior, interpretation: str) -> dict[str, object]:
        covariance = result.orbital_covariance
        return {
            **summarize_mass_posterior(result.samples),
            "orbital_parameter_names": list(covariance.parameter_names),
            "orbital_covariance": covariance.covariance.tolist(),
            "orbital_correlation": covariance.correlation.tolist(),
            "covariance_regularized": covariance.regularized,
            "bit_index": covariance.bit_index,
            "corr_vec_decoding_mode": covariance.decoding_mode,
            "corr_vec_raw_length": covariance.raw_vector_length,
            "corr_vec_coefficient_count": covariance.coefficient_count,
            "physical_draw_acceptance_fraction": result.acceptance_fraction,
            "interpretation": interpretation,
        }

    return {
        "minimum_mass": package(
            edge_on,
            "edge-on minimum-mass distribution using bit-index-validated Gaia corr_vec",
        ),
        "isotropic_sensitivity": {
            **package(
                isotropic,
                "geometry-only isotropic sensitivity using bit-index-validated Gaia corr_vec; not selection-corrected",
            ),
            "minimum_inclination_deg": minimum_isotropic_inclination_deg,
        },
    }
