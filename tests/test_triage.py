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
        "gaia_contamination_high_risk_count": 0,
        "gaia_contamination_caution_count": 0,
        "gaia_contamination_context_count": 0,
        "roche_status": "detached_geometry_consistent",
        "filling_q16": 0.1,
        "filling_q50": 0.2,
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


def test_high_risk_contamination_blocks_mass_followup_rank() -> None:
    row = _good_row()
    row["gaia_contamination_high_risk_count"] = 2
    row["gaia_contamination_caution_count"] = 1
    result = triage_followup(row)
    assert result["triage_stage"] == "contamination_resolution_hold"
    assert result["triage_rank"] == 3
    assert "gaia_high_risk_contamination_signal_count=2" in result["blockers"]
    assert "gaia_contamination_caution_signal_count=1" in result["cautions"]


def test_missing_contamination_audit_fails_closed() -> None:
    row = _good_row()
    del row["gaia_contamination_high_risk_count"]
    result = triage_followup(row)
    assert result["triage_stage"] == "contamination_resolution_hold"
    assert "gaia_contamination_audit_missing" in result["blockers"]


def test_caution_and_context_signals_do_not_block() -> None:
    row = _good_row()
    row["gaia_contamination_caution_count"] = 2
    row["gaia_contamination_context_count"] = 1
    result = triage_followup(row)
    assert result["triage_stage"] == "very_high_minimum_mass_followup"
    assert "gaia_contamination_caution_signal_count=2" in result["cautions"]
    assert "gaia_nss_context_signal_count=1" in result["cautions"]


def test_missing_roche_geometry_fails_closed() -> None:
    row = _good_row()
    del row["roche_status"]
    result = triage_followup(row)
    assert result["triage_stage"] == "roche_geometry_hold"
    assert "roche_geometry_audit_missing_or_failed" in result["blockers"]


def test_geometry_inconsistency_blocks_high_mass_followup() -> None:
    row = _good_row()
    row["roche_status"] = "geometry_inconsistent"
    row["filling_q16"] = 1.2
    row["filling_q50"] = 2.0
    result = triage_followup(row)
    assert result["triage_stage"] == "roche_geometry_hold"
    assert result["triage_rank"] == 4
    assert "primary_overfills_periastron_roche_lobe" in result["blockers"]
    assert "roche_filling_q16_above_unity" in result["blockers"]


def test_near_roche_lobe_is_retained_with_caution() -> None:
    row = _good_row()
    row["roche_status"] = "near_or_overflowing_roche_lobe"
    row["filling_q16"] = 0.6
    row["filling_q50"] = 0.9
    result = triage_followup(row)
    assert result["triage_stage"] == "very_high_minimum_mass_followup"
    assert "primary_near_periastron_roche_lobe" in result["cautions"]
    assert "roche_filling_median_above_0p8" in result["cautions"]


def test_threshold_configuration_is_validated() -> None:
    try:
        TriageConfig(high_minimum_mass_q16_solar=4.0, very_high_minimum_mass_q16_solar=3.0)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid mass thresholds were accepted")
