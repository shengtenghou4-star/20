from hou_compact.candidate_dossier import (
    DossierConfig,
    build_candidate_dossier,
    evidence_gate_summary,
    stable_blind_identifier,
)


def _complete_row() -> dict[str, object]:
    return {
        "source_id": 123,
        "solution_id": 456,
        "triage_stage": "very_high_minimum_mass_followup",
        "triage_rank": 6,
        "nss_solution_type": "SB1",
        "significance": 20.0,
        "conf_spectro_period": 0.999,
        "rv_n_good_obs_primary": 20,
        "period": 10.0,
        "semi_amplitude_primary": 80.0,
        "eccentricity": 0.1,
        "orbit_status": "scored",
        "n_clean_epochs": 4,
        "baseline_days": 100.0,
        "phase_coverage": 0.5,
        "delta_chi2_constant_minus_orbit": 40.0,
        "orbit_reduced_chi2": 1.2,
        "max_pairwise_rv_significance": 12.0,
        "primary_status": "scored",
        "method": "gaia_flame_mass_percentile_prior",
        "primary_mass_solar": 1.1,
        "fractional_68_width": 0.2,
        "mass_status": "scored",
        "minimum_m2_q16_solar": 3.5,
        "minimum_m2_q50_solar": 4.0,
        "gaia_contamination_status": "context_signals_only",
        "gaia_contamination_high_risk_count": 0,
        "gaia_contamination_caution_count": 0,
        "gaia_contamination_context_count": 1,
        "spectral_evidence_status": "no_two_component_preference",
        "sed_evidence_status": "no_composite_sed_preference",
        "novelty_status": "novelty_review_passed",
        "hierarchy_rejection_status": "alternatives_not_preferred",
        "blockers": "",
        "cautions": "independent_followup_required",
    }


def test_blind_identifier_is_stable_and_keyed() -> None:
    first = stable_blind_identifier(123, 456, b"a" * 32)
    second = stable_blind_identifier(123, 456, b"a" * 32)
    other = stable_blind_identifier(123, 456, b"b" * 32)
    assert first == second
    assert first != other
    assert first.startswith("HC-")
    assert "123" not in first


def test_blind_identifier_rejects_short_key() -> None:
    try:
        stable_blind_identifier(1, 2, b"short")
    except ValueError as error:
        assert "at least 16 bytes" in str(error)
    else:
        raise AssertionError("short HMAC key was accepted")


def test_complete_row_passes_all_evidence_gates() -> None:
    gates = evidence_gate_summary(_complete_row())
    assert len(gates) == 8
    assert all(item["passed"] is True for item in gates)


def test_missing_external_tests_remain_pending() -> None:
    row = _complete_row()
    del row["spectral_evidence_status"]
    del row["sed_evidence_status"]
    del row["novelty_status"]
    del row["hierarchy_rejection_status"]
    gates = evidence_gate_summary(row)
    pending = [item["gate"] for item in gates if item["passed"] is None]
    assert "Double-lined spectral test" in pending
    assert "Composite SED test" in pending
    assert "Known-system / novelty audit" in pending
    assert "Triple / stripped-star alternatives" in pending


def test_dossier_is_redacted_and_claim_bounded_by_default() -> None:
    content = build_candidate_dossier(
        _complete_row(),
        dossier_id="HC-ABCDEF123456",
        generated_utc="2026-07-22T00:00:00+00:00",
    )
    assert "HC-ABCDEF123456" in content
    assert "Source identifiers: redacted by default" in content
    assert "Gaia DR3 source ID" not in content
    assert "not a black-hole" in content
    assert "Passed: **8**" in content


def test_private_mode_includes_identifiers_explicitly() -> None:
    content = build_candidate_dossier(
        _complete_row(),
        dossier_id="HC-PRIVATE",
        config=DossierConfig(include_source_identifiers=True),
        generated_utc="2026-07-22T00:00:00+00:00",
    )
    assert "Gaia DR3 source ID: `123`" in content
    assert "Gaia NSS solution ID: `456`" in content


def test_high_risk_contamination_holds_gate() -> None:
    row = _complete_row()
    row["gaia_contamination_high_risk_count"] = 1
    gates = evidence_gate_summary(row)
    contamination = next(
        item for item in gates if item["gate"] == "Gaia high-risk contamination cleared"
    )
    assert contamination["passed"] is False
