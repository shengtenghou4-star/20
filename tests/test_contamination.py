from hou_compact.contamination import (
    ContaminationConfig,
    audit_gaia_contamination,
)


def _clean_row() -> dict[str, object]:
    return {
        "duplicated_source": False,
        "ipd_frac_multi_peak": 0.0,
        "ipd_frac_odd_win": 0.0,
        "ipd_gof_harmonic_amplitude": 0.0,
        "astrometric_excess_noise_sig": 0.0,
        "phot_bp_n_obs": 100,
        "phot_rp_n_obs": 100,
        "phot_bp_n_blended_transits": 0,
        "phot_rp_n_blended_transits": 0,
        "phot_bp_n_contaminated_transits": 0,
        "phot_rp_n_contaminated_transits": 0,
        "rv_nb_transits": 20,
        "rv_nb_deblended_transits": 0,
        "phot_variable_flag": "CONSTANT",
        "has_xp_continuous": True,
        "has_xp_sampled": False,
        "has_rvs": True,
    }


def test_clean_complete_row_has_no_gaia_side_signal() -> None:
    result = audit_gaia_contamination(_clean_row())
    assert result["gaia_contamination_status"] == "no_gaia_side_signal_detected"
    assert result["gaia_contamination_signal_count"] == 0
    assert "retrieve_gaia_xp_spectrum" in result["required_follow_up_checks"]
    assert "retrieve_gaia_mean_rvs_spectrum" in result["required_follow_up_checks"]


def test_blend_and_duplicate_signals_are_retained() -> None:
    row = _clean_row()
    row.update(
        {
            "duplicated_source": True,
            "ipd_frac_multi_peak": 10.0,
            "phot_bp_n_blended_transits": 20,
            "phot_variable_flag": "VARIABLE",
        }
    )
    result = audit_gaia_contamination(row)
    assert result["gaia_contamination_status"] == "contamination_signals_present"
    signals = result["gaia_contamination_signals"]
    assert "gaia_duplicated_source" in signals
    assert "ipd_multi_peak_above_caution" in signals
    assert "bp_blended_transit_fraction_above_caution" in signals
    assert "gaia_photometric_variable" in signals


def test_missing_fields_do_not_create_false_clean_status() -> None:
    result = audit_gaia_contamination({})
    assert result["gaia_contamination_status"] == (
        "no_signal_in_available_fields_but_incomplete"
    )
    assert result["gaia_contamination_missing_fields"]


def test_not_available_variability_is_incomplete_not_clean() -> None:
    row = _clean_row()
    row["phot_variable_flag"] = "NOT_AVAILABLE"
    result = audit_gaia_contamination(row)
    assert result["gaia_contamination_status"] == (
        "no_signal_in_available_fields_but_incomplete"
    )
    assert "phot_variable_flag_not_available" in result[
        "gaia_contamination_missing_fields"
    ]


def test_deblended_rv_fraction_is_computed() -> None:
    row = _clean_row()
    row["rv_nb_deblended_transits"] = 5
    result = audit_gaia_contamination(row)
    assert result["deblended_rv_fraction"] == 0.25
    assert "deblended_rv_fraction_above_caution" in result[
        "gaia_contamination_signals"
    ]


def test_configuration_validates_fraction_thresholds() -> None:
    try:
        ContaminationConfig(blended_transit_fraction_caution=1.1)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid fraction threshold was accepted")
