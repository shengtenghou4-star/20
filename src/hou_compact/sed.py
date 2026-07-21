"""Single-star versus composite broad-band SED evidence for HOU-COMPACT WP5.

The module operates on flux vectors and a caller-supplied stellar template library. It
compares one non-negative template scale with a two-template non-negative mixture using
BIC. Extinction, distance, model-grid, and calibration choices remain external and must
be recorded by the production pipeline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import nnls


@dataclass(frozen=True)
class SedFit:
    """Best weighted SED fit for one or two templates."""

    template_indices: tuple[int, ...]
    template_labels: tuple[str, ...]
    coefficients: tuple[float, ...]
    chi2: float
    degrees_of_freedom: int
    bic: float
    n_bands: int


@dataclass(frozen=True)
class SedMultiplicityEvidence:
    """Comparison of best one-template and two-template SED models."""

    single: SedFit
    composite: SedFit
    delta_bic_single_minus_composite: float
    secondary_flux_fraction: float
    evidence_status: str


def _prepare_sed(
    flux: np.ndarray,
    flux_error: np.ndarray,
    template_fluxes: np.ndarray,
    template_labels: Sequence[str] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[str, ...]]:
    observed = np.asarray(flux, dtype=float)
    errors = np.asarray(flux_error, dtype=float)
    templates = np.asarray(template_fluxes, dtype=float)
    if observed.ndim != 1 or errors.ndim != 1:
        raise ValueError("flux and flux_error must be one-dimensional")
    if observed.size != errors.size:
        raise ValueError("flux and flux_error must have equal length")
    if observed.size < 4:
        raise ValueError("at least four photometric bands are required")
    if templates.ndim != 2 or templates.shape[1] != observed.size:
        raise ValueError("template_fluxes must have shape (n_templates, n_bands)")
    if templates.shape[0] < 2:
        raise ValueError("at least two templates are required")
    if np.any(~np.isfinite(observed)) or np.any(~np.isfinite(errors)):
        raise ValueError("observed fluxes and errors must be finite")
    if np.any(errors <= 0):
        raise ValueError("flux errors must be positive")
    if np.any(~np.isfinite(templates)) or np.any(templates < 0):
        raise ValueError("template fluxes must be finite and non-negative")
    if np.any(np.sum(templates, axis=1) <= 0):
        raise ValueError("every template must have positive total flux")
    if template_labels is None:
        labels = tuple(f"template_{index}" for index in range(templates.shape[0]))
    else:
        labels = tuple(str(label) for label in template_labels)
        if len(labels) != templates.shape[0]:
            raise ValueError("template_labels length must equal number of templates")
    return observed, errors, templates, labels


def _fit_nonnegative_templates(
    observed: np.ndarray,
    errors: np.ndarray,
    design: np.ndarray,
    *,
    template_indices: tuple[int, ...],
    labels: tuple[str, ...],
) -> SedFit:
    weight = 1.0 / errors
    coefficients, _ = nnls(design * weight[:, None], observed * weight)
    model = design @ coefficients
    chi2 = float(np.sum(((observed - model) / errors) ** 2))
    n_bands = observed.size
    n_linear_parameters = design.shape[1]
    dof = n_bands - n_linear_parameters
    if dof <= 0:
        raise ValueError("not enough bands for the requested SED model")
    # Template identity is selected from a finite library; count only fitted continuous
    # coefficients here and preserve the explicit grid search in the audit trail.
    bic = chi2 + n_linear_parameters * math.log(n_bands)
    return SedFit(
        template_indices=template_indices,
        template_labels=tuple(labels[index] for index in template_indices),
        coefficients=tuple(float(value) for value in coefficients),
        chi2=chi2,
        degrees_of_freedom=dof,
        bic=bic,
        n_bands=n_bands,
    )


def fit_single_sed(
    flux: np.ndarray,
    flux_error: np.ndarray,
    template_fluxes: np.ndarray,
    template_labels: Sequence[str] | None = None,
) -> SedFit:
    """Return the best one-template non-negative scale fit."""
    observed, errors, templates, labels = _prepare_sed(
        flux, flux_error, template_fluxes, template_labels
    )
    best: SedFit | None = None
    for index in range(templates.shape[0]):
        candidate = _fit_nonnegative_templates(
            observed,
            errors,
            templates[index][:, None],
            template_indices=(index,),
            labels=labels,
        )
        if best is None or candidate.bic < best.bic:
            best = candidate
    assert best is not None
    return best


def fit_composite_sed(
    flux: np.ndarray,
    flux_error: np.ndarray,
    template_fluxes: np.ndarray,
    template_labels: Sequence[str] | None = None,
    *,
    allow_same_template_pair: bool = False,
) -> SedFit:
    """Return the best two-template non-negative mixture fit."""
    observed, errors, templates, labels = _prepare_sed(
        flux, flux_error, template_fluxes, template_labels
    )
    best: SedFit | None = None
    for first in range(templates.shape[0]):
        start = first if allow_same_template_pair else first + 1
        for second in range(start, templates.shape[0]):
            design = np.column_stack([templates[first], templates[second]])
            candidate = _fit_nonnegative_templates(
                observed,
                errors,
                design,
                template_indices=(first, second),
                labels=labels,
            )
            if best is None or candidate.bic < best.bic:
                best = candidate
    if best is None:
        raise RuntimeError("no valid two-template SED pair was available")
    return best


def compare_single_and_composite_sed(
    flux: np.ndarray,
    flux_error: np.ndarray,
    template_fluxes: np.ndarray,
    template_labels: Sequence[str] | None = None,
    *,
    strong_delta_bic: float = 10.0,
    minimum_secondary_flux_fraction: float = 0.05,
) -> SedMultiplicityEvidence:
    """Compare one- and two-template SED fits using conservative evidence gates."""
    if not math.isfinite(strong_delta_bic) or strong_delta_bic <= 0:
        raise ValueError("strong_delta_bic must be finite and positive")
    if not 0 <= minimum_secondary_flux_fraction <= 0.5:
        raise ValueError("minimum_secondary_flux_fraction must lie in [0, 0.5]")
    single = fit_single_sed(flux, flux_error, template_fluxes, template_labels)
    composite = fit_composite_sed(flux, flux_error, template_fluxes, template_labels)
    coefficients = np.asarray(composite.coefficients, dtype=float)
    total = float(np.sum(coefficients))
    secondary_fraction = float(np.min(coefficients) / total) if total > 0 else 0.0
    delta_bic = single.bic - composite.bic
    if (
        delta_bic >= strong_delta_bic
        and secondary_fraction >= minimum_secondary_flux_fraction
    ):
        status = "strong_composite_sed_evidence"
    elif delta_bic > 0 and secondary_fraction > 0:
        status = "weak_composite_sed_evidence"
    else:
        status = "no_composite_sed_preference"
    return SedMultiplicityEvidence(
        single=single,
        composite=composite,
        delta_bic_single_minus_composite=delta_bic,
        secondary_flux_fraction=secondary_fraction,
        evidence_status=status,
    )
