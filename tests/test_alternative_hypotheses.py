import pytest

from hou_compact.alternative_hypotheses import (
    AlternativeHypothesisConfig,
    audit_alternative_hypotheses,
)


def _checks(outcome: str = "disfavors") -> list[dict[str, object]]:
    hierarchy = [
        "high_resolution_imaging",
        "long_baseline_rv_trend",
        "astrometric_acceleration",
        "third_light_or_composite_sed",
    ]
    stripped = [
        "uv_excess",
        "helium_or_abundance_spectrum",
        "hot_component_sed",
        "stellar_evolution_consistency",
    ]
    records = [
        {
            "hypothesis": "hierarchy",
            "check_name": check,
            "outcome": outcome,
            "reference": f"hierarchy:{check}",
        }
        for check in hierarchy
    ]
    records.extend(
        {
            "hypothesis": "stripped_star",
            "check_name": check,
            "outcome": outcome,
            "reference": f"stripped:{check}",
        }
        for check in stripped
    )
    return records


def test_all_mandatory_checks_can_disfavor_both_alternatives() -> None:
    result = audit_alternative_hypotheses(_checks())
    assert result["hierarchy_audit_status"] == "hierarchy_disfavored"
    assert result["stripped_star_audit_status"] == "stripped_star_disfavored"
    assert result["hierarchy_missing_checks"] == ""
    assert result["stripped_star_missing_checks"] == ""


def test_supporting_check_overrides_missing_checks() -> None:
    records = _checks()
    records = [
        record
        for record in records
        if not (
            record["hypothesis"] == "hierarchy"
            and record["check_name"] == "astrometric_acceleration"
        )
    ]
    records.append(
        {
            "hypothesis": "hierarchical triple",
            "check_name": "high_resolution_imaging",
            "outcome": "supports",
            "reference": "AO companion at 0.2 arcsec",
        }
    )
    records = [
        record
        for index, record in enumerate(records)
        if not (
            index == 0
            and record["hypothesis"] == "hierarchy"
            and record["check_name"] == "high_resolution_imaging"
        )
    ]
    result = audit_alternative_hypotheses(records)
    assert result["hierarchy_audit_status"] == "hierarchy_supported"
    assert "high_resolution_imaging" in result["hierarchy_supporting_checks"]


def test_missing_required_check_keeps_hypothesis_incomplete() -> None:
    records = [
        record
        for record in _checks()
        if not (
            record["hypothesis"] == "stripped_star"
            and record["check_name"] == "uv_excess"
        )
    ]
    result = audit_alternative_hypotheses(records)
    assert result["stripped_star_audit_status"] == "stripped_star_audit_incomplete"
    assert "uv_excess" in result["stripped_star_missing_checks"]


def test_complete_neutral_checks_mean_no_support_not_disfavored() -> None:
    result = audit_alternative_hypotheses(_checks(outcome="neutral"))
    assert result["hierarchy_audit_status"] == "no_hierarchy_support"
    assert result["stripped_star_audit_status"] == "no_stripped_star_support"


def test_duplicate_check_is_rejected() -> None:
    records = _checks()
    records.append(dict(records[0]))
    with pytest.raises(ValueError, match="duplicate hierarchy check"):
        audit_alternative_hypotheses(records)


def test_invalid_hypothesis_and_outcome_are_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported alternative hypothesis"):
        audit_alternative_hypotheses(
            [{"hypothesis": "planet", "check_name": "x", "outcome": "neutral"}]
        )
    with pytest.raises(ValueError, match="unsupported check outcome"):
        audit_alternative_hypotheses(
            [{"hypothesis": "hierarchy", "check_name": "x", "outcome": "maybe"}]
        )


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        AlternativeHypothesisConfig(hierarchy_required_checks=())
    with pytest.raises(ValueError):
        AlternativeHypothesisConfig(
            stripped_star_required_checks=("uv_excess", "UV excess")
        )
