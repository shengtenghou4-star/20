"""Gaia-side blend, multiplicity, and fit-context evidence for HOU-COMPACT WP5.

This module does not decide whether a companion is luminous or compact. It separates
strong blend/multiplicity indicators from cautionary diagnostics and context signals that
are common in non-single-star samples, so the audit remains discriminating instead of
classifying nearly every SB1 as contaminated.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ContaminationConfig:
    """Pilot thresholds for descriptive Gaia contamination signals."""

    ipd_multi_peak_percent_caution: float = 2.0
    ipd_odd_window_percent_caution: float = 5.0
    ipd_harmonic_amplitude_caution: float = 0.1
    astrometric_excess_noise_significance_caution: float = 2.0
    blended_transit_fraction_caution: float = 0.05
    contaminated_transit_fraction_caution: float = 0.05
    deblended_rv_fraction_caution: float = 0.10

    def __post_init__(self) -> None:
        if self.ipd_multi_peak_percent_caution < 0:
            raise ValueError("ipd_multi_peak_percent_caution must be non-negative")
        if self.ipd_odd_window_percent_caution < 0:
            raise ValueError("ipd_odd_window_percent_caution must be non-negative")
        if self.ipd_harmonic_amplitude_caution < 0:
            raise ValueError("ipd_harmonic_amplitude_caution must be non-negative")
        if self.astrometric_excess_noise_significance_caution < 0:
            raise ValueError(
                "astrometric_excess_noise_significance_caution must be non-negative"
            )
        for name, value in (
            ("blended_transit_fraction_caution", self.blended_transit_fraction_caution),
            (
                "contaminated_transit_fraction_caution",
                self.contaminated_transit_fraction_caution,
            ),
            ("deblended_rv_fraction_caution", self.deblended_rv_fraction_caution),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must lie in [0, 1]")


def _float(row: Mapping[str, object], key: str) -> float | None:
    try:
        value = float(row.get(key))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _integer(row: Mapping[str, object], key: str) -> int | None:
    try:
        value = int(row.get(key))
    except (TypeError, ValueError):
        return None
    return value


def _boolean(row: Mapping[str, object], key: str) -> bool | None:
    value = row.get(key)
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _fraction(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or numerator < 0 or denominator <= 0:
        return None
    return numerator / denominator


def audit_gaia_contamination(
    row: Mapping[str, object],
    config: ContaminationConfig = ContaminationConfig(),
) -> dict[str, object]:
    """Return tiered Gaia-side contamination evidence and pending audit tasks.

    Tiers are descriptive, not calibrated probabilities:

    - ``high_risk``: direct image/photometric blend, contamination, or duplicate evidence;
    - ``caution``: diagnostics that require follow-up but are not decisive alone;
    - ``context``: signals expected to be common in an NSS-selected sample and therefore
      retained for model checking without being counted as contamination by themselves.
    """
    high_risk: list[str] = []
    caution: list[str] = []
    context: list[str] = []
    missing: list[str] = []
    follow_up: list[str] = [
        "inspect_gaia_and_survey_images",
        "test_composite_or_double_lined_spectrum",
        "fit_single_vs_composite_sed",
        "check_known_binary_and_variable_catalogues",
        "test_hierarchical_triple_and_stripped_star_models",
    ]

    duplicated = _boolean(row, "duplicated_source")
    if duplicated is None:
        missing.append("duplicated_source")
    elif duplicated:
        high_risk.append("gaia_duplicated_source")

    multi_peak = _float(row, "ipd_frac_multi_peak")
    if multi_peak is None:
        missing.append("ipd_frac_multi_peak")
    elif multi_peak >= config.ipd_multi_peak_percent_caution:
        high_risk.append("ipd_multi_peak_above_caution")

    odd_window = _float(row, "ipd_frac_odd_win")
    if odd_window is None:
        missing.append("ipd_frac_odd_win")
    elif odd_window >= config.ipd_odd_window_percent_caution:
        caution.append("ipd_odd_window_above_caution")

    harmonic = _float(row, "ipd_gof_harmonic_amplitude")
    if harmonic is None:
        missing.append("ipd_gof_harmonic_amplitude")
    elif harmonic >= config.ipd_harmonic_amplitude_caution:
        caution.append("ipd_scan_angle_structure_above_caution")

    excess_sig = _float(row, "astrometric_excess_noise_sig")
    if excess_sig is None:
        missing.append("astrometric_excess_noise_sig")
    elif excess_sig >= config.astrometric_excess_noise_significance_caution:
        # Excess noise is common by construction in non-single-star samples. It is useful
        # orbit-fit context, not independent evidence of a luminous contaminant.
        context.append("astrometric_excess_noise_significant")

    bp_obs = _integer(row, "phot_bp_n_obs")
    rp_obs = _integer(row, "phot_rp_n_obs")
    bp_blended = _integer(row, "phot_bp_n_blended_transits")
    rp_blended = _integer(row, "phot_rp_n_blended_transits")
    bp_contaminated = _integer(row, "phot_bp_n_contaminated_transits")
    rp_contaminated = _integer(row, "phot_rp_n_contaminated_transits")
    bp_blend_fraction = _fraction(bp_blended, bp_obs)
    rp_blend_fraction = _fraction(rp_blended, rp_obs)
    bp_contamination_fraction = _fraction(bp_contaminated, bp_obs)
    rp_contamination_fraction = _fraction(rp_contaminated, rp_obs)

    for name, value in (
        ("bp_blended_transit_fraction", bp_blend_fraction),
        ("rp_blended_transit_fraction", rp_blend_fraction),
    ):
        if value is None:
            missing.append(name)
        elif value >= config.blended_transit_fraction_caution:
            high_risk.append(name + "_above_caution")

    for name, value in (
        ("bp_contaminated_transit_fraction", bp_contamination_fraction),
        ("rp_contaminated_transit_fraction", rp_contamination_fraction),
    ):
        if value is None:
            missing.append(name)
        elif value >= config.contaminated_transit_fraction_caution:
            high_risk.append(name + "_above_caution")

    rv_transits = _integer(row, "rv_nb_transits")
    deblended_rv_transits = _integer(row, "rv_nb_deblended_transits")
    deblended_rv_fraction = _fraction(deblended_rv_transits, rv_transits)
    if deblended_rv_fraction is None:
        missing.append("deblended_rv_fraction")
    elif deblended_rv_fraction >= config.deblended_rv_fraction_caution:
        caution.append("deblended_rv_fraction_above_caution")

    variable_flag = str(row.get("phot_variable_flag", "")).strip().upper()
    if not variable_flag or variable_flag == "NOT_AVAILABLE":
        missing.append("phot_variable_flag_not_available")
    elif variable_flag == "VARIABLE":
        caution.append("gaia_photometric_variable")
    elif variable_flag != "CONSTANT":
        missing.append("phot_variable_flag_unrecognized")

    has_xp = _boolean(row, "has_xp_continuous") or _boolean(row, "has_xp_sampled")
    has_rvs = _boolean(row, "has_rvs")
    if has_xp:
        follow_up.append("retrieve_gaia_xp_spectrum")
    if has_rvs:
        follow_up.append("retrieve_gaia_mean_rvs_spectrum")

    high_risk = sorted(set(high_risk))
    caution = sorted(set(caution))
    context = sorted(set(context))
    all_signals = sorted(set(high_risk + caution + context))
    if high_risk:
        status = "high_risk_blend_or_multiplicity_signal"
    elif caution:
        status = "caution_signals_only"
    elif context:
        status = "context_signals_only"
    elif missing:
        status = "no_signal_in_available_fields_but_incomplete"
    else:
        status = "no_gaia_side_signal_detected"

    return {
        "gaia_contamination_status": status,
        "gaia_contamination_signal_count": len(all_signals),
        "gaia_contamination_signals": ";".join(all_signals),
        "gaia_contamination_high_risk_count": len(high_risk),
        "gaia_contamination_high_risk_signals": ";".join(high_risk),
        "gaia_contamination_caution_count": len(caution),
        "gaia_contamination_caution_signals": ";".join(caution),
        "gaia_contamination_context_count": len(context),
        "gaia_contamination_context_signals": ";".join(context),
        "gaia_contamination_missing_fields": ";".join(sorted(set(missing))),
        "bp_blended_transit_fraction": bp_blend_fraction,
        "rp_blended_transit_fraction": rp_blend_fraction,
        "bp_contaminated_transit_fraction": bp_contamination_fraction,
        "rp_contaminated_transit_fraction": rp_contamination_fraction,
        "deblended_rv_fraction": deblended_rv_fraction,
        "required_follow_up_checks": ";".join(sorted(set(follow_up))),
        "interpretation_boundary": (
            "High-risk signals indicate possible blending or multiplicity; caution and "
            "context tiers are not vetoes. Absence of a signal does not exclude a luminous "
            "secondary or hierarchy."
        ),
    }
