from hou_compact.triage import TriageConfig, decode_set_flag_bits, triage_followup


def _good_row() -> dict[str, object]:
    return {
        "significance": 20.0,
        "conf_spectro_period": 0.999,
        "rv_n_good_obs_primary": 20,
        "flags": 0,
        "orbit_status": "scored",
        "n_clean_epochs": 4,
        "phase_coverage": 0.5,
        "delta_chi2_constant_minus_orbit": 40.0,
        "orbit_reduced_chi2": 1.2,
        "primary_status": "scored",
        "fractional_68_width": 0.2,
        "mass_status": "scored",
        "minimum_m2_q16_solar": 3.5,
        "minimum_m2_q50_solar": 4.0,
    }


def test_decode_flag_bits() -> None:
    assert decode_set_flag_bits((1 << 8) | (1 << 24)) == (8, 24)


def test_gaia_fatal_flag_blocks_before_desi() -> None:
    row = _good_row()
    row["flags"] = 1 << 13
    result = triage_followup(row)
    assert result["triage_stage"] == "gaia_quality_hold"
    assert "gaia_fatal_flag_bits=13" in result["blockers"]


def test_caution_flag_does_not_fake_a_blocker() -> None:
    row = _good_row()
    row["flags"] = 1 << 24
    result = triage_followup(row)
    assert result["triage_stage"] == "very_high_minimum_mass_followup"
    assert "gaia_caution_flag_bits=24" in result["cautions"]


def test_insufficient_desi_support_is_held() -> None:
    row = _good_row()
    row["n_clean_epochs"] = 2
    result = triage_followup(row)
    assert result["triage_stage"] == "desi_orbit_hold"
    assert "clean_desi_epoch_count_below_gate_or_missing" in result["blockers"]


def test_high_mass_gate_uses_lower_16th_percentile() -> None:
    row = _good_row()
    row["minimum_m2_q16_solar"] = 1.6
    row["minimum_m2_q50_solar"] = 6.0
    result = triage_followup(row)
    assert result["triage_stage"] == "high_minimum_mass_followup"


def test_large_median_does_not_override_low_q16() -> None:
    row = _good_row()
    row["minimum_m2_q16_solar"] = 1.0
    row["minimum_m2_q50_solar"] = 8.0
    result = triage_followup(row)
    assert result["triage_stage"] == "orbit_supported_lower_mass"


def test_threshold_configuration_is_validated() -> None:
    try:
        TriageConfig(high_minimum_mass_q16_solar=4.0, very_high_minimum_mass_q16_solar=3.0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid mass thresholds were accepted")
