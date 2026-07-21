import pytest

from hou_compact.novelty import NoveltyConfig, audit_novelty_records


SERVICES = ("SIMBAD", "VizieR", "ADS")


def test_complete_search_without_matches_is_clean_but_not_classifying() -> None:
    result = audit_novelty_records([], searched_services=SERVICES)
    assert result["novelty_audit_status"] == "no_prior_compact_object_claim_found"
    assert result["novelty_match_count"] == 0
    assert "does not prove astrophysical novelty" in result[
        "novelty_interpretation_boundary"
    ]


def test_missing_required_service_keeps_audit_incomplete() -> None:
    result = audit_novelty_records([], searched_services=("SIMBAD", "VizieR"))
    assert result["novelty_audit_status"] == "novelty_audit_incomplete"
    assert result["novelty_missing_services"] == "ADS"


def test_prior_black_hole_claim_has_priority_over_binary_record() -> None:
    records = [
        {
            "service": "SIMBAD",
            "object_id": "Example-1",
            "object_type": "spectroscopic binary",
            "separation_arcsec": 0.2,
        },
        {
            "service": "ADS",
            "bibcode": "2025TEST....1A",
            "title": "A dormant black hole candidate in a binary",
            "separation_arcsec": 0.0,
        },
    ]
    result = audit_novelty_records(records, searched_services=SERVICES)
    assert result["novelty_audit_status"] == "prior_compact_object_claim_found"
    assert result["novelty_compact_claim_count"] == 1
    assert result["novelty_known_binary_count"] == 1
    assert "2025TEST....1A" in result["novelty_bibcodes"]


def test_known_binary_without_compact_claim_is_retained_as_caution_status() -> None:
    records = [
        {
            "service": "SIMBAD",
            "object_id": "Example-SB1",
            "object_type": "SB1",
            "separation_arcsec": 0.1,
        }
    ]
    result = audit_novelty_records(records, searched_services=SERVICES)
    assert result["novelty_audit_status"] == (
        "known_binary_without_compact_object_claim"
    )
    assert result["novelty_known_binary_count"] == 1


def test_large_separation_match_is_not_used_as_precedence() -> None:
    records = [
        {
            "service": "ADS",
            "title": "Black hole candidate",
            "separation_arcsec": 20.0,
        }
    ]
    result = audit_novelty_records(records, searched_services=SERVICES)
    assert result["novelty_audit_status"] == "no_prior_compact_object_claim_found"
    assert result["novelty_rejected_large_separation_count"] == 1
    assert result["novelty_compact_claim_count"] == 0


def test_invalid_config_is_rejected() -> None:
    with pytest.raises(ValueError):
        NoveltyConfig(required_services=())
    with pytest.raises(ValueError):
        NoveltyConfig(maximum_match_separation_arcsec=0.0)
