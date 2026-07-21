import pytest

from hou_compact.candidate_cards import (
    CandidateCardConfig,
    build_candidate_card,
    candidate_card_eligibility,
    candidate_pseudonym,
)


def _eligible_row() -> dict[str, object]:
    return {
        "source_id": 123456789,
        "solution_id": 42,
        "triage_rank": 5,
        "triage_stage": "very_high_minimum_mass_followup",
        "blockers": "",
        "orbit_status": "scored",
        "mass_status": "scored",
        "gaia_contamination_status": "contamination_signals_present",
        "nss_solution_type": "SB1",
        "minimum_m2_q16_solar": 3.2,
        "minimum_m2_q50_solar": 4.0,
        "minimum_m2_q84_solar": 5.0,
        "gaia_ra": 10.0,
        "gaia_dec": -3.0,
    }


def test_pseudonym_is_deterministic_and_salted() -> None:
    first = candidate_pseudonym(1, 2, salt="alpha")
    second = candidate_pseudonym(1, 2, salt="alpha")
    other = candidate_pseudonym(1, 2, salt="beta")
    assert first == second
    assert first != other
    assert first.startswith("HOUC-")


def test_default_card_does_not_expose_source_id() -> None:
    card = build_candidate_card(_eligible_row(), salt="private-salt")
    assert "source_id" not in card["identity"]
    assert card["identity"]["candidate_id"].startswith("HOUC-")
    assert card["claim_status"] == "private_followup_target_only"


def test_explicit_private_identity_mode_can_include_source_id() -> None:
    config = CandidateCardConfig(include_source_id=True)
    card = build_candidate_card(_eligible_row(), salt="private-salt", config=config)
    assert card["identity"]["source_id"] == 123456789


def test_blocked_row_is_ineligible() -> None:
    row = _eligible_row()
    row["blockers"] = "primary_mass_prior_too_broad"
    eligible, reasons = candidate_card_eligibility(row)
    assert eligible is False
    assert "unresolved_stage_blockers" in reasons
    with pytest.raises(ValueError, match="not eligible"):
        build_candidate_card(row, salt="private-salt")


def test_low_triage_rank_is_ineligible() -> None:
    row = _eligible_row()
    row["triage_rank"] = 3
    eligible, reasons = candidate_card_eligibility(row)
    assert eligible is False
    assert "triage_rank_below_private_card_gate" in reasons


def test_config_rejects_weak_pseudonym_length() -> None:
    with pytest.raises(ValueError):
        CandidateCardConfig(pseudonym_length=4)
