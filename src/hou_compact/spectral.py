"""Template-based spectral multiplicity evidence for HOU-COMPACT WP5.

The routines compare one shifted stellar template with a two-shift mixture on a fixed
velocity grid. They produce evidence for or against unresolved line multiplicity; they
do not identify a compact object or a stellar type.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

_SPEED_OF_LIGHT_KMS = 299_792.458


@dataclass(frozen=True)
class TemplateFit:
    """Best weighted template fit on a discrete velocity grid."""

    velocities_kms: tuple[float, ...]
    amplitudes: tuple[float, ...]
    continuum: float
    chi2: float
    degrees_of_freedom: int
    bic: float
    n_pixels: int


@dataclass(frozen=True)
class SpectralMultiplicityEvidence:
    """One- versus two-component template comparison."""

    single: TemplateFit
    double: TemplateFit
    delta_bic_single_minus_double: float
    velocity_separation_kms: float
    secondary_to_primary_amplitude: float
    evidence_status: str


def relativistic_doppler_factor(velocity_kms: float) -> float:
    """Return the wavelength factor for a radial velocity using the relativistic form."""
    if not math.isfinite(velocity_kms):
        raise ValueError("velocity_kms must be finite")
    beta = velocity_kms / _SPEED_OF_LIGHT_KMS
    if abs(beta) >= 1:
        raise ValueError("absolute radial velocity must be below the speed of light")
    return math.sqrt((1.0 + beta) / (1.0 - beta))


def shift_template(
    wavelength: np.ndarray,
    template_wavelength: np.ndarray,
    template_flux: np.ndarray,
    velocity_kms: float,
) -> np.ndarray:
    """Evaluate a rest-frame template on an observed wavelength grid at one velocity."""
    observed = np.asarray(wavelength, dtype=float)
    rest_grid = np.asarray(template_wavelength, dtype=float)
    rest_flux = np.asarray(template_flux, dtype=float)
    if observed.ndim != 1 or rest_grid.ndim != 1 or rest_flux.ndim != 1:
        raise ValueError("wavelength and template arrays must be one-dimensional")
    if rest_grid.size != rest_flux.size or rest_grid.size < 2:
        raise ValueError("template wavelength and flux must have equal length >= 2")
    if np.any(~np.isfinite(observed)) or np.any(~np.isfinite(rest_grid)):
        raise ValueError("wavelength grids must be finite")
    if np.any(np.diff(rest_grid) <= 0) or np.any(np.diff(observed) <= 0):
        raise ValueError("wavelength grids must be strictly increasing")
    if np.any(~np.isfinite(rest_flux)):
        raise ValueError("template flux must be finite")
    factor = relativistic_doppler_factor(velocity_kms)
    rest_coordinate = observed / factor
    return np.interp(rest_coordinate, rest_grid, rest_flux, left=np.nan, right=np.nan)


def _prepare_pixels(
    wavelength: np.ndarray,
    flux: np.ndarray,
    inverse_variance: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    wavelength = np.asarray(wavelength, dtype=float)
    flux = np.asarray(flux, dtype=float)
    inverse_variance = np.asarray(inverse_variance, dtype=float)
    if wavelength.ndim != 1 or flux.ndim != 1 or inverse_variance.ndim != 1:
        raise ValueError("spectrum arrays must be one-dimensional")
    if not (wavelength.size == flux.size == inverse_variance.size):
        raise ValueError("spectrum arrays must have equal length")
    if wavelength.size < 20:
        raise ValueError("at least 20 spectral pixels are required")
    if np.any(np.diff(wavelength) <= 0):
        raise ValueError("wavelength must be strictly increasing")
    valid = (
        np.isfinite(wavelength)
        & np.isfinite(flux)
        & np.isfinite(inverse_variance)
        & (inverse_variance > 0)
    )
    if int(np.sum(valid)) < 20:
        raise ValueError("fewer than 20 finite positive-weight pixels remain")
    return wavelength[valid], flux[valid], inverse_variance[valid]


def _validate_velocity_grid(velocity_grid_kms: np.ndarray) -> np.ndarray:
    grid = np.asarray(velocity_grid_kms, dtype=float)
    if grid.ndim != 1 or grid.size < 3:
        raise ValueError("velocity grid must be one-dimensional with at least 3 values")
    if np.any(~np.isfinite(grid)) or np.any(np.diff(grid) <= 0):
        raise ValueError("velocity grid must be finite and strictly increasing")
    return grid


def _weighted_nonnegative_fit(
    flux: np.ndarray,
    inverse_variance: np.ndarray,
    template_components: list[np.ndarray],
    *,
    velocity_parameter_count: int,
) -> tuple[tuple[float, ...], float, float, int, float, int]:
    """Fit non-negative line amplitudes plus an unrestricted constant continuum."""
    finite = np.isfinite(flux) & np.isfinite(inverse_variance)
    for component in template_components:
        finite &= np.isfinite(component)
    if int(np.sum(finite)) < 20:
        raise ValueError("template overlap leaves fewer than 20 usable pixels")

    y = flux[finite]
    weight = np.sqrt(inverse_variance[finite])
    deviations = [1.0 - component[finite] for component in template_components]
    # Split the constant into positive and negative columns so NNLS can represent an
    # unrestricted continuum offset without allowing unphysical negative line depths.
    design = np.column_stack([*deviations, np.ones_like(y), -np.ones_like(y)])
    coefficients, _ = nnls(design * weight[:, None], (1.0 - y) * weight)
    amplitudes = tuple(float(value) for value in coefficients[: len(deviations)])
    continuum_offset = float(coefficients[-2] - coefficients[-1])
    model = 1.0 - continuum_offset
    for amplitude, deviation in zip(amplitudes, deviations, strict=True):
        model = model - amplitude * deviation
    residual = y - model
    chi2 = float(np.sum(inverse_variance[finite] * residual**2))
    n_pixels = len(y)
    fitted_linear_parameters = len(deviations) + 1
    dof = n_pixels - fitted_linear_parameters
    if dof <= 0:
        raise ValueError("not enough pixels for the requested template model")
    parameter_count = fitted_linear_parameters + velocity_parameter_count
    bic = chi2 + parameter_count * math.log(n_pixels)
    continuum = 1.0 - continuum_offset
    return amplitudes, continuum, chi2, dof, bic, n_pixels


def fit_single_template(
    wavelength: np.ndarray,
    flux: np.ndarray,
    inverse_variance: np.ndarray,
    template_wavelength: np.ndarray,
    template_flux: np.ndarray,
    velocity_grid_kms: np.ndarray,
) -> TemplateFit:
    """Return the best one-template fit on a discrete velocity grid."""
    wavelength, flux, inverse_variance = _prepare_pixels(
        wavelength, flux, inverse_variance
    )
    grid = _validate_velocity_grid(velocity_grid_kms)
    best: TemplateFit | None = None
    for velocity in grid:
        shifted = shift_template(
            wavelength, template_wavelength, template_flux, float(velocity)
        )
        try:
            amplitudes, continuum, chi2, dof, bic, n_pixels = _weighted_nonnegative_fit(
                flux,
                inverse_variance,
                [shifted],
                velocity_parameter_count=1,
            )
        except ValueError:
            continue
        candidate = TemplateFit(
            velocities_kms=(float(velocity),),
            amplitudes=amplitudes,
            continuum=continuum,
            chi2=chi2,
            degrees_of_freedom=dof,
            bic=bic,
            n_pixels=n_pixels,
        )
        if best is None or candidate.bic < best.bic:
            best = candidate
    if best is None:
        raise RuntimeError("no valid single-template fit on the velocity grid")
    return best


def fit_double_template(
    wavelength: np.ndarray,
    flux: np.ndarray,
    inverse_variance: np.ndarray,
    template_wavelength: np.ndarray,
    template_flux: np.ndarray,
    velocity_grid_kms: np.ndarray,
    *,
    minimum_separation_kms: float = 40.0,
) -> TemplateFit:
    """Return the best two-template fit with a minimum velocity separation."""
    wavelength, flux, inverse_variance = _prepare_pixels(
        wavelength, flux, inverse_variance
    )
    grid = _validate_velocity_grid(velocity_grid_kms)
    if not math.isfinite(minimum_separation_kms) or minimum_separation_kms <= 0:
        raise ValueError("minimum_separation_kms must be finite and positive")
    shifted_templates = {
        float(velocity): shift_template(
            wavelength, template_wavelength, template_flux, float(velocity)
        )
        for velocity in grid
    }
    best: TemplateFit | None = None
    for index, first_velocity in enumerate(grid[:-1]):
        for second_velocity in grid[index + 1 :]:
            if second_velocity - first_velocity < minimum_separation_kms:
                continue
            try:
                amplitudes, continuum, chi2, dof, bic, n_pixels = (
                    _weighted_nonnegative_fit(
                        flux,
                        inverse_variance,
                        [
                            shifted_templates[float(first_velocity)],
                            shifted_templates[float(second_velocity)],
                        ],
                        velocity_parameter_count=2,
                    )
                )
            except ValueError:
                continue
            candidate = TemplateFit(
                velocities_kms=(float(first_velocity), float(second_velocity)),
                amplitudes=amplitudes,
                continuum=continuum,
                chi2=chi2,
                degrees_of_freedom=dof,
                bic=bic,
                n_pixels=n_pixels,
            )
            if best is None or candidate.bic < best.bic:
                best = candidate
    if best is None:
        raise RuntimeError("no valid separated two-template fit on the velocity grid")
    return best


def compare_single_and_double_templates(
    wavelength: np.ndarray,
    flux: np.ndarray,
    inverse_variance: np.ndarray,
    template_wavelength: np.ndarray,
    template_flux: np.ndarray,
    velocity_grid_kms: np.ndarray,
    *,
    minimum_separation_kms: float = 40.0,
    strong_delta_bic: float = 10.0,
    minimum_secondary_ratio: float = 0.10,
) -> SpectralMultiplicityEvidence:
    """Compare one- and two-component fits and return conservative evidence status."""
    single = fit_single_template(
        wavelength,
        flux,
        inverse_variance,
        template_wavelength,
        template_flux,
        velocity_grid_kms,
    )
    double = fit_double_template(
        wavelength,
        flux,
        inverse_variance,
        template_wavelength,
        template_flux,
        velocity_grid_kms,
        minimum_separation_kms=minimum_separation_kms,
    )
    delta_bic = single.bic - double.bic
    separation = abs(double.velocities_kms[1] - double.velocities_kms[0])
    primary_amplitude = max(double.amplitudes)
    secondary_amplitude = min(double.amplitudes)
    ratio = secondary_amplitude / primary_amplitude if primary_amplitude > 0 else 0.0
    if delta_bic >= strong_delta_bic and ratio >= minimum_secondary_ratio:
        status = "strong_two_component_spectral_evidence"
    elif delta_bic > 0 and ratio > 0:
        status = "weak_two_component_spectral_evidence"
    else:
        status = "no_two_component_preference"
    return SpectralMultiplicityEvidence(
        single=single,
        double=double,
        delta_bic_single_minus_double=delta_bic,
        velocity_separation_kms=separation,
        secondary_to_primary_amplitude=ratio,
        evidence_status=status,
    )
