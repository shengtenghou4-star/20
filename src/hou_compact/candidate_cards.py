"""Private follow-up candidate-card construction for HOU-COMPACT.

Cards summarize evidence and unresolved checks. They use deterministic pseudonyms by
default so novelty-sensitive source identifiers are not accidentally copied into public
reports or issue threads.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateCardConfig:
    """Eligibility and privacy settings for private candidate cards."""

    minimum_triage_rank: int = 4
    pseudonym_prefix: str = "HOUC"
    pseudonym_length: int = 12
    include_source_id: bool = False

    def __post_init__(self) -> None:
        if self.minimum_triage_rank < 0:
            raise ValueError("minimum_triage_rank must be non-negative")
        if not self.pseudonym_prefix or not self.pseudonym_prefix.isalnum():
            raise ValueError("pseudonym_prefix must be non-empty and alphanumeric")
        if not 8 <= self.pseudonym_length <= 32:
            raise ValueError("pseudonym_length must be in [8, 32]")


def candidate_pseudonym(
    source_id: object,
    solution_id: object,
    *,
    salt: str,
    prefix: str = "HOUC",
    length: int = 12,
) -> str:
    """Return a deterministic salted pseudonym for a source/solution pair."""
    if not salt:
        raise ValueError("a non-empty salt is required")
    payload = f"{salt}|{source_id}|{solution_id}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def _finite(row: Mapping[str, object], key: str) -> float | None:
    try:
        value = float(row.get(key))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _integer(row: Mapping[str, object], key: str) -> int | None:
    try:
        return int(row.get(key))
    except (TypeError, ValueError):
        return None


def _boolean(row: Mapping[str, object], key: str) -> bool | None:
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        if hasattr(value, "item"):
            value = value.item()
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def candidate_card_eligibility(
    row: Mapping[str, object],
    config: CandidateCardConfig = CandidateCardConfig(),
) -> tuple[bool, tuple[str, ...]]:
    """Check whether a row may enter the private candidate-card queue."""
    reasons: list[str] = []
    source_id = _integer(row, "source_id")
    solution_id = _integer(row, "solution_id")
    triage_rank = _integer(row, "triage_rank")
    blockers = str(row.get("blockers", "")).strip()
    orbit_status = str(row.get("orbit_status", "")).strip()
    mass_status = str(row.get("mass_status", "")).strip()
    contamination_status = str(row.get("gaia_contamination_status", "")).strip()

    if source_id is None or solution_id is None:
        reasons.append("source_or_solution_identifier_missing")
    if triage_rank is None or triage_rank < config.minimum_triage_rank:
        reasons.append("triage_rank_below_private_card_gate")
    if blockers:
        reasons.append("unresolved_stage_blockers")
    if orbit_status != "scored":
        reasons.append("orbit_product_not_scored")
    if mass_status != "scored":
        reasons.append("correlated_mass_product_not_scored")
    if not contamination_status:
        reasons.append("gaia_contamination_audit_missing")
    return not reasons, tuple(reasons)


def build_candidate_card(
    row: Mapping[str, object],
    *,
    salt: str,
    config: CandidateCardConfig = CandidateCardConfig(),
) -> dict[str, object]:
    """Build a structured private follow-up card from merged evidence."""
    eligible, reasons = candidate_card_eligibility(row, config)
    if not eligible:
        raise ValueError("row is not eligible: " + ";".join(reasons))

    source_id = _integer(row, "source_id")
    solution_id = _integer(row, "solution_id")
    assert source_id is not None
    assert solution_id is not None
    pseudonym = candidate_pseudonym(
        source_id,
        solution_id,
        salt=salt,
        prefix=config.pseudonym_prefix,
        length=config.pseudonym_length,
    )
    identity: dict[str, object] = {
        "candidate_id": pseudonym,
        "solution_id": solution_id,
    }
    if config.include_source_id:
        identity["source_id"] = source_id

    card: dict[str, object] = {
        "schema_version": "0.1",
        "identity": identity,
        "position": {
            "ra_deg": _finite(row, "gaia_ra"),
            "dec_deg": _finite(row, "gaia_dec"),
            "parallax_mas": _finite(row, "gaia_parallax"),
            "g_mag": _finite(row, "phot_g_mean_mag"),
            "bp_rp_mag": _finite(row, "bp_rp"),
        },
        "gaia_orbit": {
            "solution_type": str(row.get("nss_solution_type", "")),
            "period_days": _finite(row, "period"),
            "k1_kms": _finite(row, "semi_amplitude_primary"),
            "eccentricity": _finite(row, "eccentricity"),
            "significance": _finite(row, "significance"),
            "period_confidence": _finite(row, "conf_spectro_period"),
            "flags": _integer(row, "flags"),
        },
        "independent_desi_orbit": {
            "clean_epochs": _integer(row, "n_clean_epochs"),
            "phase_coverage": _finite(row, "phase_coverage"),
            "delta_chi2_constant_minus_orbit": _finite(
                row, "delta_chi2_constant_minus_orbit"
            ),
            "orbit_reduced_chi2": _finite(row, "orbit_reduced_chi2"),
            "systemic_velocity_kms": _finite(
                row, "orbit_systemic_velocity_kms"
            ),
        },
        "mass_inference": {
            "primary_mass_median_solar": _finite(row, "primary_mass_solar"),
            "primary_mass_fractional_68_width": _finite(
                row, "fractional_68_width"
            ),
            "minimum_m2_q16_solar": _finite(row, "minimum_m2_q16_solar"),
            "minimum_m2_q50_solar": _finite(row, "minimum_m2_q50_solar"),
            "minimum_m2_q84_solar": _finite(row, "minimum_m2_q84_solar"),
            "covariance_mode": str(row.get("orbital_covariance_mode", "")),
            "covariance_regularized": _boolean(
                row, "minimum_covariance_regularized"
            ),
            "physical_draw_acceptance_fraction": _finite(
                row, "minimum_physical_draw_acceptance_fraction"
            ),
        },
        "contamination_audit": {
            "gaia_status": str(row.get("gaia_contamination_status", "")),
            "signal_count": _integer(row, "gaia_contamination_signal_count"),
            "signals": str(row.get("gaia_contamination_signals", "")),
            "missing_fields": str(
                row.get("gaia_contamination_missing_fields", "")
            ),
            "required_follow_up_checks": str(
                row.get("required_follow_up_checks", "")
            ),
        },
        "triage": {
            "stage": str(row.get("triage_stage", "")),
            "rank": _integer(row, "triage_rank"),
            "passed_gates": str(row.get("passed_gates", "")),
            "cautions": str(row.get("cautions", "")),
        },
        "claim_status": "private_followup_target_only",
        "interpretation_boundary": (
            "This card is not a compact-object classification. Image, spectrum, SED, "
            "hierarchy, primary-mass, catalogue, and novelty checks remain mandatory."
        ),
    }
    json.dumps(card, allow_nan=False)
    return card
