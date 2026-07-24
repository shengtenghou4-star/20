#!/usr/bin/env python3
"""Per-source fail-closed adapter for formal Gaia covariance mass vetting.

The formal covariance gate requires a positive published Gaia FLAME lower primary-mass
bound. A missing lower bound must never be replaced by the nominal mass because that can
inflate the inferred companion mass. Instead, the affected candidate is retained in the
encrypted source-level table, marked non-evaluable, and treated as a non-survivor while
other candidates continue through the unchanged covariance calculation.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import gaia_covariance_vetting as _legacy

_ORIGINAL_EVALUATE_SOURCE = _legacy._evaluate_source
_ORIGINAL_AUGMENT_PRODUCTS = _legacy.augment_covariance_phase_products
_MISSING_FLAME_ERROR = "missing required mass_flame_lower"
_MISSING_FLAME_REASON = "missing_mass_flame_lower"


def _non_evaluable_source(
    grow: dict[str, str],
    prow: dict[str, str],
    *,
    draws: int,
    parity_tolerance: float,
) -> dict[str, Any]:
    """Build a parity-checked non-survivor record without inventing a stellar mass."""
    source = _legacy._exact_id(grow.get("source_id"), label="candidate source")
    solution = str(grow.get("nss_solution_type", "")).strip()
    parity = _legacy.compare_with_nsstools(grow)
    if parity.maximum_absolute_difference > parity_tolerance:
        raise _legacy.GaiaCovarianceVettingError(
            "HOU-COMPACT covariance decode disagrees with nsstools: "
            f"{parity.maximum_absolute_difference}"
        )

    period_error = _legacy._finite(grow.get("period_error"), label="period_error")
    k1_error = _legacy._finite(
        grow.get("semi_amplitude_primary_error"),
        label="semi_amplitude_primary_error",
    )
    eccentricity_error = (
        0.0
        if solution == "SB1C"
        else _legacy._finite(
            grow.get("eccentricity_error"),
            label="eccentricity_error",
        )
    )
    covariance = _legacy.sb1_mass_parameter_covariance(
        solution_type=solution,
        bit_index=grow.get("bit_index"),
        corr_vec=grow.get("corr_vec"),
        period_error=period_error,
        k1_error=k1_error,
        eccentricity_error=eccentricity_error,
    )
    return {
        "source_id": source,
        "gaia_covariance_reference_api": parity.reference_api,
        "gaia_covariance_reference_max_abs_difference": (
            parity.maximum_absolute_difference
        ),
        "gaia_covariance_decoding_mode": covariance.decoding_mode,
        "gaia_covariance_regularized": covariance.regularized,
        "gaia_covariance_raw_vector_length": covariance.raw_vector_length,
        "gaia_covariance_draws_requested": draws,
        "gaia_covariance_draws_physical": None,
        "gaia_covariance_physical_draw_fraction": None,
        "gaia_covariance_mass_evaluable": False,
        "gaia_covariance_mass_non_evaluable_reason": _MISSING_FLAME_REASON,
        "minimum_companion_mass_covariance_q15_865_solar": None,
        "minimum_companion_mass_covariance_q2_275_solar": None,
        "minimum_companion_mass_covariance_q0_135_solar": None,
        "minimum_companion_mass_covariance_median_solar": None,
        "probability_minimum_companion_mass_at_least_1_4": None,
        "probability_minimum_companion_mass_at_least_3": None,
        "covariance_q15_865_strict_phase_mass3": False,
        "covariance_q2_275_strict_phase_mass3": False,
        "covariance_q0_135_strict_phase_mass3": False,
        "nominal_promoted_source": _legacy._truth(
            prow.get("nominal_strict_phase_mass3")
        ),
    }


def _evaluate_source_failclosed(
    grow: dict[str, str],
    prow: dict[str, str],
    *,
    draws: int,
    global_seed: int,
    parity_tolerance: float,
) -> dict[str, Any]:
    try:
        result = _ORIGINAL_EVALUATE_SOURCE(
            grow,
            prow,
            draws=draws,
            global_seed=global_seed,
            parity_tolerance=parity_tolerance,
        )
    except _legacy.GaiaCovarianceVettingError as error:
        if str(error) != _MISSING_FLAME_ERROR:
            raise
        return _non_evaluable_source(
            grow,
            prow,
            draws=draws,
            parity_tolerance=parity_tolerance,
        )
    result["gaia_covariance_mass_evaluable"] = True
    result["gaia_covariance_mass_non_evaluable_reason"] = ""
    return result


# The legacy aggregate function resolves this global at call time, so patching it keeps
# every existing numerical and output path unchanged for evaluable candidates.
_legacy._evaluate_source = _evaluate_source_failclosed


def _source_level_evaluable_counts(phase_rows: Path) -> tuple[int, int]:
    evaluable = 0
    missing_flame = 0
    with phase_rows.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        for row in reader:
            if str(row.get("gaia_covariance_mass_evaluable", "")).strip().lower() in {
                "1",
                "true",
                "yes",
                "y",
            }:
                evaluable += 1
            if (
                str(row.get("gaia_covariance_mass_non_evaluable_reason", "")).strip()
                == _MISSING_FLAME_REASON
            ):
                missing_flame += 1
    return evaluable, missing_flame


def augment_covariance_phase_products(
    *,
    candidate_gaia: Path,
    phase_rows: Path,
    phase_summary: Path,
    draws: int = 200_000,
    global_seed: int = 20260724,
    parity_tolerance: float = 1e-10,
) -> dict[str, Any]:
    """Run the unchanged gate and append aggregate per-source evaluability counts."""
    result = _ORIGINAL_AUGMENT_PRODUCTS(
        candidate_gaia=candidate_gaia,
        phase_rows=phase_rows,
        phase_summary=phase_summary,
        draws=draws,
        global_seed=global_seed,
        parity_tolerance=parity_tolerance,
    )
    evaluable, missing_flame = _source_level_evaluable_counts(phase_rows)
    total = int(result["candidate_sources"])
    result.update(
        {
            "schema_version": "0.2",
            "sources_covariance_mass_evaluable": evaluable,
            "sources_covariance_mass_not_evaluable": total - evaluable,
            "sources_missing_positive_flame_lower_mass": missing_flame,
            "draws_per_evaluable_source": draws,
        }
    )
    contract = result.get("contract")
    if isinstance(contract, dict):
        contract["missing_primary_mass"] = (
            "candidate retained but covariance mass is non-evaluable and every "
            "mass-threshold survivor flag fails closed"
        )

    summary = json.loads(phase_summary.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or summary.get("candidate_safe") is not True:
        raise _legacy.GaiaCovarianceVettingError(
            "phase summary is not candidate-safe"
        )
    summary["gaia_covariance_vetting"] = result
    phase_summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result
