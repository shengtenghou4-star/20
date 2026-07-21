"""Final evidence gate for HOU-COMPACT follow-up targets.

This module never classifies an object as a compact object. It determines whether the
minimum evidence package needed for a serious claim audit is complete, whether luminous
companion evidence already explains the signal, or which checks remain unresolved.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimReadinessConfig:
    """Frozen pilot policy for advancing a private target to claim-audit review."""

    minimum_triage_rank: int = 4
    accepted_no_secondary_spectral_statuses: tuple[str, ...] = (
        "no_two_component_preference",
    )
    accepted_no_secondary_sed_statuses: tuple[str, ...] = (
        "no_composite_sed_preference",
    )
    accepted_hierarchy_statuses: tuple[str, ...] = (
        "no_hierarchy_support",
        "hierarchy_disfavored",
    )
    accepted_stripped_star_statuses: tuple[str, ...] = (
        "no_stripped_star_support",
        "stripped_star_disfavored",
    )
    accepted_novelty_statuses: tuple[str, ...] = (
        "no_prior_compact_object_claim_found",
        "known_binary_without_compact_object_claim",
    )
    accepted_primary_statuses: tuple[str, ...] = (
        "independent_primary_mass_scored",
        "independent_primary_mass_scored_with_caution",
    )

    def __post_init__(self) -> None:
        if self.minimum_triage_rank < 0:
            raise ValueError("minimum_triage_rank must be non-negative")
        for name, values in (
            (
                "accepted_no_secondary_spectral_statuses",
                self.accepted_no_secondary_spectral_statuses,
            ),
            (
                "accepted_no_secondary_sed_statuses",
                self.accepted_no_secondary_sed_statuses,
            ),
            ("accepted_hierarchy_statuses", self.accepted_hierarchy_statuses),
            ("accepted_stripped_star_statuses", self.accepted_stripped_star_statuses),
            ("accepted_novelty_statuses", self.accepted_novelty_statuses),
            ("accepted_primary_statuses", self.accepted_primary_statuses),
        ):
            if not values or any(not value for value in values):
                raise ValueError(f"{name} must contain non-empty statuses")


def _integer(row: Mapping[str, object], key: str) -> int | None:
    try:
        return int(row.get(key))
    except (TypeError, ValueError):
        return None


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    text = str(value).strip()
    if text.casefold() in {"nan", "nat", "<na>", "none"}:
        return ""
    return text


def assess_claim_readiness(
    row: Mapping[str, object],
    config: ClaimReadinessConfig = ClaimReadinessConfig(),
) -> dict[str, object]:
    """Return a deterministic final-audit status with explicit evidence reasons.

    The strongest possible result is ``claim_audit_ready_not_classified``. This means the
    required rejection and novelty checks are present; it is not an astrophysical class.
    """

    blockers: list[str] = []
    cautions: list[str] = []
    passed: list[str] = []

    triage_rank = _integer(row, "triage_rank")
    triage_blockers = _text(row, "blockers")
    orbit_status = _text(row, "orbit_status")
    mass_status = _text(row, "mass_status")

    if triage_rank is None or triage_rank < config.minimum_triage_rank:
        blockers.append("triage_rank_below_claim_audit_gate")
    if triage_blockers:
        blockers.append("upstream_triage_blockers_unresolved")
    if orbit_status != "scored":
        blockers.append("independent_orbit_product_not_scored")
    if mass_status != "scored":
        blockers.append("correlated_mass_product_not_scored")

    if blockers:
        return {
            "claim_readiness_status": "upstream_evidence_incomplete",
            "claim_readiness_rank": 0,
            "claim_readiness_passed": "",
            "claim_readiness_blockers": ";".join(blockers),
            "claim_readiness_cautions": "",
            "claim_authorized": False,
        }
    passed.append("upstream_orbit_and_mass")

    contamination_status = _text(row, "gaia_contamination_status")
    contamination_resolution = _text(row, "gaia_contamination_resolution")
    if not contamination_status:
        blockers.append("gaia_contamination_audit_missing")
    elif contamination_status == "contamination_signals_present":
        if contamination_resolution not in {
            "signals_explained_without_luminous_companion",
            "signals_resolved_by_followup",
        }:
            blockers.append("gaia_contamination_signals_unresolved")
        else:
            cautions.append(
                "gaia_contamination_signals_resolved_with_documented_followup"
            )
    elif contamination_status == "no_signal_in_available_fields_but_incomplete":
        blockers.append("gaia_contamination_audit_incomplete")
    elif contamination_status != "no_gaia_side_signal_detected":
        blockers.append("gaia_contamination_status_unrecognized")
    else:
        passed.append("gaia_contamination_screen")

    spectral_status = _text(row, "spectral_evidence_status")
    sed_status = _text(row, "sed_evidence_status")
    strong_spectral = spectral_status == "strong_two_component_spectral_evidence"
    strong_sed = sed_status == "strong_composite_sed_evidence"
    if strong_spectral or strong_sed:
        reasons = []
        if strong_spectral:
            reasons.append("strong_two_component_spectral_evidence")
        if strong_sed:
            reasons.append("strong_composite_sed_evidence")
        return {
            "claim_readiness_status": "luminous_companion_evidence_present",
            "claim_readiness_rank": 1,
            "claim_readiness_passed": ";".join(passed),
            "claim_readiness_blockers": ";".join(reasons),
            "claim_readiness_cautions": ";".join(cautions),
            "claim_authorized": False,
        }

    if spectral_status not in config.accepted_no_secondary_spectral_statuses:
        if spectral_status == "weak_two_component_spectral_evidence":
            blockers.append("weak_two_component_spectral_evidence_unresolved")
        elif not spectral_status:
            blockers.append("spectral_multiplicity_audit_missing")
        else:
            blockers.append("spectral_multiplicity_status_unaccepted")
    else:
        passed.append("spectral_no_luminous_secondary_preference")

    if sed_status not in config.accepted_no_secondary_sed_statuses:
        if sed_status == "weak_composite_sed_evidence":
            blockers.append("weak_composite_sed_evidence_unresolved")
        elif not sed_status:
            blockers.append("composite_sed_audit_missing")
        else:
            blockers.append("composite_sed_status_unaccepted")
    else:
        passed.append("sed_no_luminous_secondary_preference")

    primary_status = _text(row, "independent_primary_status")
    if primary_status not in config.accepted_primary_statuses:
        blockers.append("independent_primary_mass_not_ready")
    else:
        passed.append("independent_primary_mass")
        if primary_status.endswith("with_caution"):
            cautions.append("independent_primary_mass_has_documented_caution")

    hierarchy_status = _text(row, "hierarchy_audit_status")
    if hierarchy_status not in config.accepted_hierarchy_statuses:
        blockers.append("hierarchical_multiple_hypothesis_unresolved")
    else:
        passed.append("hierarchy_audit")

    stripped_status = _text(row, "stripped_star_audit_status")
    if stripped_status not in config.accepted_stripped_star_statuses:
        blockers.append("stripped_star_hypothesis_unresolved")
    else:
        passed.append("stripped_star_audit")

    novelty_status = _text(row, "novelty_audit_status")
    if novelty_status == "prior_compact_object_claim_found":
        blockers.append("prior_compact_object_claim_found")
    elif novelty_status not in config.accepted_novelty_statuses:
        blockers.append("catalogue_and_literature_novelty_audit_incomplete")
    else:
        passed.append("catalogue_and_literature_novelty")
        if novelty_status == "known_binary_without_compact_object_claim":
            cautions.append(
                "known_binary_record_requires_citation_and_reconciliation"
            )

    if blockers:
        return {
            "claim_readiness_status": "claim_audit_incomplete",
            "claim_readiness_rank": 2,
            "claim_readiness_passed": ";".join(passed),
            "claim_readiness_blockers": ";".join(blockers),
            "claim_readiness_cautions": ";".join(cautions),
            "claim_authorized": False,
        }

    return {
        "claim_readiness_status": "claim_audit_ready_not_classified",
        "claim_readiness_rank": 3,
        "claim_readiness_passed": ";".join(passed),
        "claim_readiness_blockers": "",
        "claim_readiness_cautions": ";".join(cautions),
        "claim_authorized": False,
    }
