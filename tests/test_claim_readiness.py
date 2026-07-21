import pytest

from hou_compact.claim_readiness import (
    ClaimReadinessConfig,
    assess_claim_readiness,
)


def _ready_row() -> dict[str, object]:
    return {
        "triage_rank": 5,
        "blockers": "",
        "orbit_status": "scored",
        "mass_status": "scored",
        "gaia_contamination_status": "no_gaia_side_signal_detected",
        "spectral_evidence_status": "no_two_component_preference",
        "sed_evidence_status": "no_composite_sed_preference",
        "independent_primary_status": "independent_primary_mass_scored",
        "hierarchy_audit_status": "hierarchy_disfavored",
        "stripped_star_audit_status": "stripped_star_disfavored",
        "novelty_audit_status": "no_prior_compact_object_claim_found",
    }


def test_upstream_evidence_blocks_final_audit() -> None:
    row = _ready_row()
    row["triage_rank"] = 2
    row["orbit_status"] = "insufficient_clean_epochs"
    result = assess_claim_readiness(row)
    assert result["claim_readiness_status"] == "upstream_evidence_incomplete"
    assert "triage_rank_below_claim_audit_gate" in result["claim_readiness_blockers"]
    assert "independent_orbit_product_not_scored" in result[
        "claim_readiness_blockers"
    ]
    assert result["claim_authorized"] is False


def test_strong_spectral_secondary_evidence_stops_claim_path() -> None:
    row = _ready_row()
    row["spectral_evidence_status"] = "strong_two_component_spectral_evidence"
    result = assess_claim_readiness(row)
    assert result["claim_readiness_status"] == "luminous_companion_evidence_present"
    assert result["claim_readiness_rank"] == 1
    assert "strong_two_component_spectral_evidence" in result[
        "claim_readiness_blockers"
    ]


def test_missing_rejection_audits_remain_incomplete() -> None:
    row = _ready_row()
    row.pop("sed_evidence_status")
    row.pop("hierarchy_audit_status")
    result = assess_claim_readiness(row)
    assert result["claim_readiness_status"] == "claim_audit_incomplete"
    assert "composite_sed_audit_missing" in result["claim_readiness_blockers"]
    assert "hierarchical_multiple_hypothesis_unresolved" in result[
        "claim_readiness_blockers"
    ]


def test_all_required_evidence_reaches_nonclassification_ready_state() -> None:
    result = assess_claim_readiness(_ready_row())
    assert result["claim_readiness_status"] == "claim_audit_ready_not_classified"
    assert result["claim_readiness_rank"] == 3
    assert result["claim_readiness_blockers"] == ""
    assert result["claim_authorized"] is False
    assert "catalogue_and_literature_novelty" in result["claim_readiness_passed"]


def test_prior_claim_prevents_novelty_advancement() -> None:
    row = _ready_row()
    row["novelty_audit_status"] = "prior_compact_object_claim_found"
    result = assess_claim_readiness(row)
    assert result["claim_readiness_status"] == "claim_audit_incomplete"
    assert "prior_compact_object_claim_found" in result["claim_readiness_blockers"]


def test_resolved_gaia_contamination_signal_is_retained_as_caution() -> None:
    row = _ready_row()
    row["gaia_contamination_status"] = "contamination_signals_present"
    row["gaia_contamination_resolution"] = "signals_resolved_by_followup"
    result = assess_claim_readiness(row)
    assert result["claim_readiness_status"] == "claim_audit_ready_not_classified"
    assert "gaia_contamination_signals_resolved_with_documented_followup" in result[
        "claim_readiness_cautions"
    ]


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(ValueError):
        ClaimReadinessConfig(minimum_triage_rank=-1)
    with pytest.raises(ValueError):
        ClaimReadinessConfig(accepted_novelty_statuses=())
