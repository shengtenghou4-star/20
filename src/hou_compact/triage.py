"""Transparent stage gates for HOU-COMPACT follow-up prioritization.

The triage engine never emits a compact-object classification. It records which
independent evidence gates have passed and why an object is held back.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TriageConfig:
    """Frozen pilot thresholds for deterministic follow-up staging."""

    min_gaia_significance: float = 5.0
    min_period_confidence: float = 0.99
    min_gaia_good_rv_epochs: int = 10
    min_clean_desi_epochs: int = 3
    min_phase_coverage: float = 0.20
    min_delta_chi2: float = 9.0
    max_orbit_reduced_chi2: float = 5.0
    max_primary_fractional_68_width: float = 0.75
    high_minimum_mass_q16_solar: float = 1.4
    very_high_minimum_mass_q16_solar: float = 3.0
    fatal_gaia_flag_bits: tuple[int, ...] = (8, 9, 10, 13, 14, 15, 16, 18, 19, 21)
    caution_gaia_flag_bits: tuple[int, ...] = (11, 12, 17, 20, 22, 23, 24, 25)

    def __post_init__(self) -> None:
        if self.min_gaia_significance <= 0:
            raise ValueError("min_gaia_significance must be positive")
        if not 0 <= self.min_period_confidence <= 1:
            raise ValueError("min_period_confidence must lie in [0, 1]")
        if self.min_gaia_good_rv_epochs < 1 or self.min_clean_desi_epochs < 2:
            raise ValueError("epoch thresholds are invalid")
        if not 0 <= self.min_phase_coverage <= 1:
            raise ValueError("min_phase_coverage must lie in [0, 1]")
        if self.min_delta_chi2 < 0 or self.max_orbit_reduced_chi2 <= 0:
            raise ValueError("orbit thresholds are invalid")
        if self.max_primary_fractional_68_width <= 0:
            raise ValueError("primary-mass width threshold must be positive")
        if not 0 < self.high_minimum_mass_q16_solar < self.very_high_minimum_mass_q16_solar:
            raise ValueError("mass thresholds must be positive and increasing")


def decode_set_flag_bits(flags: int) -> tuple[int, ...]:
    """Return the set bit numbers of a non-negative integer flag field."""
    if isinstance(flags, bool) or not isinstance(flags, int):
        raise TypeError("flags must be an integer")
    if flags < 0:
        raise ValueError("flags must be non-negative")
    return tuple(index for index in range(flags.bit_length()) if flags & (1 << index))


def _finite_float(row: Mapping[str, object], key: str) -> float | None:
    value = row.get(key)
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(row: Mapping[str, object], key: str) -> int | None:
    value = row.get(key)
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result


def _result(
    *,
    stage: str,
    rank: int,
    passed: list[str],
    blockers: list[str],
    cautions: list[str],
    set_bits: tuple[int, ...],
) -> dict[str, object]:
    return {
        "triage_stage": stage,
        "triage_rank": rank,
        "passed_gates": ";".join(passed),
        "blockers": ";".join(blockers),
        "cautions": ";".join(cautions),
        "gaia_set_flag_bits": ",".join(map(str, set_bits)),
    }


def triage_followup(
    row: Mapping[str, object],
    config: TriageConfig = TriageConfig(),
) -> dict[str, object]:
    """Evaluate sequential evidence gates and return a stage plus audit reasons."""
    blockers: list[str] = []
    cautions: list[str] = []
    passed: list[str] = []

    significance = _finite_float(row, "significance")
    period_confidence = _finite_float(row, "conf_spectro_period")
    gaia_good_epochs = _integer(row, "rv_n_good_obs_primary")
    flags = _integer(row, "flags")

    if significance is None or significance < config.min_gaia_significance:
        blockers.append("gaia_significance_below_gate_or_missing")
    if period_confidence is None or period_confidence < config.min_period_confidence:
        blockers.append("gaia_period_confidence_below_gate_or_missing")
    if gaia_good_epochs is None or gaia_good_epochs < config.min_gaia_good_rv_epochs:
        blockers.append("gaia_good_rv_epoch_count_below_gate_or_missing")

    set_bits: tuple[int, ...] = ()
    if flags is None or flags < 0:
        blockers.append("gaia_flags_missing_or_invalid")
    else:
        set_bits = decode_set_flag_bits(flags)
        fatal = sorted(set(set_bits).intersection(config.fatal_gaia_flag_bits))
        caution = sorted(set(set_bits).intersection(config.caution_gaia_flag_bits))
        if fatal:
            blockers.append("gaia_fatal_flag_bits=" + ",".join(map(str, fatal)))
        if caution:
            cautions.append("gaia_caution_flag_bits=" + ",".join(map(str, caution)))

    if blockers:
        return _result(
            stage="gaia_quality_hold",
            rank=0,
            passed=[],
            blockers=blockers,
            cautions=cautions,
            set_bits=set_bits,
        )
    passed.append("gaia_quality")

    orbit_status = str(row.get("orbit_status", row.get("status", "")))
    clean_epochs = _integer(row, "n_clean_epochs")
    phase_coverage = _finite_float(row, "phase_coverage")
    delta_chi2 = _finite_float(row, "delta_chi2_constant_minus_orbit")
    orbit_reduced_chi2 = _finite_float(row, "orbit_reduced_chi2")

    if orbit_status != "scored":
        blockers.append("independent_desi_orbit_not_scored")
    if clean_epochs is None or clean_epochs < config.min_clean_desi_epochs:
        blockers.append("clean_desi_epoch_count_below_gate_or_missing")
    if phase_coverage is None or phase_coverage < config.min_phase_coverage:
        blockers.append("phase_coverage_below_gate_or_missing")
    if delta_chi2 is None or delta_chi2 < config.min_delta_chi2:
        blockers.append("fixed_gaia_orbit_not_preferred_enough")
    if orbit_reduced_chi2 is None or orbit_reduced_chi2 > config.max_orbit_reduced_chi2:
        blockers.append("fixed_gaia_orbit_absolute_fit_poor_or_missing")

    if blockers:
        return _result(
            stage="desi_orbit_hold",
            rank=1,
            passed=passed,
            blockers=blockers,
            cautions=cautions,
            set_bits=set_bits,
        )
    passed.append("independent_orbit_support")

    primary_status = str(row.get("primary_status", ""))
    primary_width = _finite_float(row, "fractional_68_width")
    if primary_status not in {"scored", "weak_prior"}:
        blockers.append("primary_mass_prior_not_scored")
    if primary_width is None or primary_width > config.max_primary_fractional_68_width:
        blockers.append("primary_mass_prior_too_broad_or_missing")
    if primary_status == "weak_prior":
        cautions.append("primary_mass_prior_marked_weak")

    mass_status = str(row.get("mass_status", ""))
    minimum_q16 = _finite_float(row, "minimum_m2_q16_solar")
    minimum_q50 = _finite_float(row, "minimum_m2_q50_solar")
    if mass_status != "scored":
        blockers.append("companion_mass_product_not_scored")
    if minimum_q16 is None or minimum_q50 is None:
        blockers.append("minimum_mass_quantiles_missing")

    if blockers:
        return _result(
            stage="mass_inference_hold",
            rank=2,
            passed=passed,
            blockers=blockers,
            cautions=cautions,
            set_bits=set_bits,
        )
    passed.append("mass_inference_ready")

    high_risk_count = _integer(row, "gaia_contamination_high_risk_count")
    caution_count = _integer(row, "gaia_contamination_caution_count")
    context_count = _integer(row, "gaia_contamination_context_count")
    if high_risk_count is None:
        blockers.append("gaia_contamination_audit_missing")
    elif high_risk_count > 0:
        blockers.append(f"gaia_high_risk_contamination_signal_count={high_risk_count}")
    if caution_count is None:
        cautions.append("gaia_contamination_caution_count_missing")
    elif caution_count > 0:
        cautions.append(f"gaia_contamination_caution_signal_count={caution_count}")
    if context_count is None:
        cautions.append("gaia_contamination_context_count_missing")
    elif context_count > 0:
        cautions.append(f"gaia_nss_context_signal_count={context_count}")

    if blockers:
        return _result(
            stage="contamination_resolution_hold",
            rank=3,
            passed=passed,
            blockers=blockers,
            cautions=cautions,
            set_bits=set_bits,
        )
    passed.append("no_high_risk_gaia_contamination_signal")

    roche_status = str(row.get("roche_status", ""))
    filling_q16 = _finite_float(row, "filling_q16")
    filling_q50 = _finite_float(row, "filling_q50")
    if roche_status in {"", "nan", "input_error"}:
        blockers.append("roche_geometry_audit_missing_or_failed")
    elif roche_status == "geometry_inconsistent":
        blockers.append("primary_overfills_periastron_roche_lobe")
    elif roche_status == "near_or_overflowing_roche_lobe":
        cautions.append("primary_near_periastron_roche_lobe")
        passed.append("roche_geometry_audited_with_contact_caution")
    elif roche_status == "detached_geometry_consistent":
        passed.append("detached_roche_geometry")
    else:
        blockers.append(f"unknown_roche_geometry_status={roche_status}")
    if filling_q16 is not None and filling_q16 > 1.0:
        blockers.append("roche_filling_q16_above_unity")
    if filling_q50 is not None and filling_q50 > 0.8:
        cautions.append("roche_filling_median_above_0p8")

    if blockers:
        return _result(
            stage="roche_geometry_hold",
            rank=4,
            passed=passed,
            blockers=blockers,
            cautions=cautions,
            set_bits=set_bits,
        )

    assert minimum_q16 is not None
    if minimum_q16 >= config.very_high_minimum_mass_q16_solar:
        stage = "very_high_minimum_mass_followup"
        rank = 7
        passed.append("minimum_mass_q16_above_very_high_gate")
    elif minimum_q16 >= config.high_minimum_mass_q16_solar:
        stage = "high_minimum_mass_followup"
        rank = 6
        passed.append("minimum_mass_q16_above_high_gate")
    else:
        stage = "orbit_supported_lower_mass"
        rank = 5
        passed.append("minimum_mass_below_high_gate")

    cautions.append("no_spectral_sed_or_hierarchy_rejection_yet")
    return _result(
        stage=stage,
        rank=rank,
        passed=passed,
        blockers=[],
        cautions=cautions,
        set_bits=set_bits,
    )
