"""Independent primary-star mass consensus for HOU-COMPACT WP6.

The routines combine already-derived mass estimates from distinct method families. They do
not create stellar parameters from photometry or spectra; callers must preserve each
method's full provenance, assumptions, and covariance. The consensus is an audit product,
not a replacement for stellar modelling.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PrimaryValidationConfig:
    """Frozen thresholds for independent primary-mass agreement."""

    minimum_method_families: int = 2
    caution_pairwise_sigma: float = 3.0
    failure_pairwise_sigma: float = 5.0
    maximum_fractional_consensus_error: float = 0.50

    def __post_init__(self) -> None:
        if self.minimum_method_families < 2:
            raise ValueError("minimum_method_families must be at least two")
        if not 0 < self.caution_pairwise_sigma < self.failure_pairwise_sigma:
            raise ValueError("pairwise sigma thresholds must be positive and increasing")
        if not 0 < self.maximum_fractional_consensus_error < 1:
            raise ValueError("maximum_fractional_consensus_error must lie in (0, 1)")


def _finite(record: Mapping[str, object], key: str) -> float | None:
    try:
        value = float(record.get(key))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def validate_primary_mass_estimates(
    estimates: Iterable[Mapping[str, object]],
    config: PrimaryValidationConfig = PrimaryValidationConfig(),
) -> dict[str, object]:
    """Combine independent symmetric mass estimates and report agreement diagnostics.

    Required estimate fields are ``method_family``, ``mass_solar`` and
    ``mass_error_solar``. Repeated rows from the same method family are rejected rather
    than counted as independent evidence.
    """

    accepted: list[dict[str, object]] = []
    rejected: list[str] = []
    seen_families: set[str] = set()
    for index, raw in enumerate(estimates):
        family = str(raw.get("method_family", "")).strip()
        mass = _finite(raw, "mass_solar")
        error = _finite(raw, "mass_error_solar")
        if not family:
            rejected.append(f"row_{index}:missing_method_family")
            continue
        normalized = family.casefold()
        if normalized in seen_families:
            raise ValueError(f"duplicate method_family: {family}")
        seen_families.add(normalized)
        if mass is None or mass <= 0:
            rejected.append(f"{family}:invalid_mass")
            continue
        if error is None or error <= 0:
            rejected.append(f"{family}:invalid_error")
            continue
        accepted.append(
            {
                "method_family": family,
                "mass_solar": mass,
                "mass_error_solar": error,
                "provenance": str(raw.get("provenance", "")).strip(),
            }
        )

    families = [record["method_family"] for record in accepted]
    if len(accepted) < config.minimum_method_families:
        return {
            "independent_primary_status": "independent_primary_mass_incomplete",
            "independent_primary_method_count": len(accepted),
            "independent_primary_methods": ";".join(families),
            "independent_primary_mass_solar": None,
            "independent_primary_mass_error_solar": None,
            "independent_primary_fractional_error": None,
            "independent_primary_max_pairwise_sigma": None,
            "independent_primary_consistency_chi2": None,
            "independent_primary_consistency_dof": None,
            "independent_primary_rejected_inputs": ";".join(rejected),
            "independent_primary_interpretation_boundary": (
                "Fewer than two valid method families; no independent consensus exists."
            ),
        }

    masses = np.asarray([record["mass_solar"] for record in accepted], dtype=float)
    errors = np.asarray(
        [record["mass_error_solar"] for record in accepted],
        dtype=float,
    )
    weights = 1.0 / errors**2
    consensus = float(np.sum(weights * masses) / np.sum(weights))
    consensus_error = float(math.sqrt(1.0 / np.sum(weights)))
    chi2 = float(np.sum(((masses - consensus) / errors) ** 2))
    dof = len(masses) - 1

    pairwise: list[float] = []
    for first in range(len(masses) - 1):
        for second in range(first + 1, len(masses)):
            denominator = math.hypot(errors[first], errors[second])
            pairwise.append(abs(masses[first] - masses[second]) / denominator)
    max_pairwise = max(pairwise, default=0.0)
    fractional_error = consensus_error / consensus

    cautions: list[str] = []
    blockers: list[str] = []
    if max_pairwise >= config.failure_pairwise_sigma:
        blockers.append("independent_primary_methods_in_severe_tension")
    elif max_pairwise >= config.caution_pairwise_sigma:
        cautions.append("independent_primary_methods_in_moderate_tension")
    if fractional_error > config.maximum_fractional_consensus_error:
        blockers.append("independent_primary_consensus_too_broad")
    if rejected:
        cautions.append("some_primary_mass_inputs_rejected")

    if blockers:
        status = "independent_primary_mass_conflicted"
    elif cautions:
        status = "independent_primary_mass_scored_with_caution"
    else:
        status = "independent_primary_mass_scored"

    return {
        "independent_primary_status": status,
        "independent_primary_method_count": len(accepted),
        "independent_primary_methods": ";".join(families),
        "independent_primary_mass_solar": consensus,
        "independent_primary_mass_error_solar": consensus_error,
        "independent_primary_fractional_error": fractional_error,
        "independent_primary_max_pairwise_sigma": max_pairwise,
        "independent_primary_consistency_chi2": chi2,
        "independent_primary_consistency_dof": dof,
        "independent_primary_blockers": ";".join(blockers),
        "independent_primary_cautions": ";".join(cautions),
        "independent_primary_rejected_inputs": ";".join(rejected),
        "independent_primary_interpretation_boundary": (
            "The weighted consensus summarizes supplied independent method families. "
            "Shared systematics, model assumptions, and unresolved companion light remain."
        ),
    }
