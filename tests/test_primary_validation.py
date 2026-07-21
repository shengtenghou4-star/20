import pytest

from hou_compact.primary_validation import (
    PrimaryValidationConfig,
    validate_primary_mass_estimates,
)


def test_two_consistent_method_families_produce_scored_consensus() -> None:
    result = validate_primary_mass_estimates(
        [
            {
                "method_family": "spectroscopic_isochrone",
                "mass_solar": 1.05,
                "mass_error_solar": 0.10,
            },
            {
                "method_family": "sed_parallax_radius_logg",
                "mass_solar": 1.00,
                "mass_error_solar": 0.12,
            },
        ]
    )
    assert result["independent_primary_status"] == "independent_primary_mass_scored"
    assert result["independent_primary_method_count"] == 2
    assert 1.0 < result["independent_primary_mass_solar"] < 1.05
    assert result["independent_primary_max_pairwise_sigma"] < 1.0


def test_moderate_method_tension_is_scored_with_caution() -> None:
    result = validate_primary_mass_estimates(
        [
            {
                "method_family": "spectroscopic_isochrone",
                "mass_solar": 1.0,
                "mass_error_solar": 0.10,
            },
            {
                "method_family": "asteroseismic",
                "mass_solar": 1.5,
                "mass_error_solar": 0.10,
            },
        ]
    )
    assert result["independent_primary_status"] == (
        "independent_primary_mass_scored_with_caution"
    )
    assert "moderate_tension" in result["independent_primary_cautions"]


def test_severe_method_tension_blocks_consensus() -> None:
    result = validate_primary_mass_estimates(
        [
            {
                "method_family": "spectroscopic_isochrone",
                "mass_solar": 0.8,
                "mass_error_solar": 0.05,
            },
            {
                "method_family": "asteroseismic",
                "mass_solar": 1.4,
                "mass_error_solar": 0.05,
            },
        ]
    )
    assert result["independent_primary_status"] == "independent_primary_mass_conflicted"
    assert "severe_tension" in result["independent_primary_blockers"]


def test_one_valid_method_family_is_incomplete() -> None:
    result = validate_primary_mass_estimates(
        [
            {
                "method_family": "spectroscopic_isochrone",
                "mass_solar": 1.0,
                "mass_error_solar": 0.1,
            },
            {
                "method_family": "bad",
                "mass_solar": -1.0,
                "mass_error_solar": 0.1,
            },
        ]
    )
    assert result["independent_primary_status"] == "independent_primary_mass_incomplete"
    assert result["independent_primary_method_count"] == 1
    assert "bad:invalid_mass" in result["independent_primary_rejected_inputs"]


def test_duplicate_method_family_is_rejected() -> None:
    estimates = [
        {
            "method_family": "isochrone",
            "mass_solar": 1.0,
            "mass_error_solar": 0.1,
        },
        {
            "method_family": "Isochrone",
            "mass_solar": 1.1,
            "mass_error_solar": 0.1,
        },
    ]
    with pytest.raises(ValueError, match="duplicate method_family"):
        validate_primary_mass_estimates(estimates)


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        PrimaryValidationConfig(minimum_method_families=1)
    with pytest.raises(ValueError):
        PrimaryValidationConfig(
            caution_pairwise_sigma=5.0,
            failure_pairwise_sigma=3.0,
        )
