import pandas as pd
import pytest

from hou_compact.attrition import (
    blocker_counts,
    candidate_safe_attrition_summary,
    clean_epoch_distribution,
    minimum_mass_threshold_counts,
    sequential_attrition,
)


def _triage_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "triage_stage": [
                "gaia_quality_hold",
                "desi_orbit_hold",
                "desi_orbit_hold",
                "mass_inference_hold",
                "contamination_resolution_hold",
                "roche_geometry_hold",
                "orbit_supported_lower_mass",
                "high_minimum_mass_followup",
                "very_high_minimum_mass_followup",
                "very_high_minimum_mass_followup",
            ],
            "blockers": [
                "bad_gaia",
                "no_desi;low_phase",
                "no_desi",
                "no_mass",
                "blend",
                "overflow",
                "",
                "",
                "",
                "",
            ],
            "cautions": [
                "",
                "",
                "weak_snr",
                "",
                "",
                "contact",
                "no_sed",
                "no_sed",
                "no_sed",
                "no_sed",
            ],
            "n_clean_epochs": [0, 0, 2, 3, 3, 4, 3, 4, 5, None],
            "minimum_m2_q16_solar": [
                None,
                None,
                None,
                None,
                4.0,
                5.0,
                1.0,
                2.0,
                4.0,
                9.0,
            ],
        }
    )


def test_sequential_attrition_counts_entered_and_advanced() -> None:
    flow = sequential_attrition(_triage_frame()).set_index("stage")
    assert flow.loc["gaia_quality_hold", "entered"] == 10
    assert flow.loc["gaia_quality_hold", "held"] == 1
    assert flow.loc["desi_orbit_hold", "entered"] == 9
    assert flow.loc["desi_orbit_hold", "held"] == 2
    assert flow.loc["roche_geometry_hold", "advanced"] == 4
    assert flow.loc["all_evidence_gates_passed", "advanced"] == 4


def test_blockers_count_all_tokens() -> None:
    counts = blocker_counts(_triage_frame())
    assert counts["no_desi"] == 2
    assert counts["low_phase"] == 1
    assert counts["overflow"] == 1


def test_clean_epoch_distribution_includes_missing() -> None:
    assert clean_epoch_distribution(_triage_frame()) == {
        "missing": 1,
        "0": 2,
        "1": 0,
        "2": 1,
        "3_plus": 6,
    }


def test_mass_threshold_counts_split_final_passes() -> None:
    counts = minimum_mass_threshold_counts(_triage_frame())
    assert counts["q16_ge_1.4_solar"] == {
        "all_finite_mass_rows": 5,
        "all_evidence_gates_passed": 3,
    }
    assert counts["q16_ge_3_solar"] == {
        "all_finite_mass_rows": 4,
        "all_evidence_gates_passed": 2,
    }
    assert counts["q16_ge_8_solar"] == {
        "all_finite_mass_rows": 1,
        "all_evidence_gates_passed": 1,
    }


def test_summary_is_candidate_safe_and_complete() -> None:
    summary = candidate_safe_attrition_summary(_triage_frame())
    assert summary["candidate_safe"] is True
    assert summary["cohort_rows"] == 10
    assert summary["all_evidence_gates_passed"] == 4
    assert "source_id" not in summary


def test_unknown_stage_fails_closed() -> None:
    frame = _triage_frame()
    frame.loc[0, "triage_stage"] = "mystery_stage"
    with pytest.raises(ValueError, match="unknown triage stages"):
        sequential_attrition(frame)


def test_final_count_must_match_advanced_population() -> None:
    frame = _triage_frame()
    frame = frame.loc[frame["triage_stage"] != "high_minimum_mass_followup"].copy()
    frame.loc[len(frame)] = {
        "triage_stage": "gaia_quality_hold",
        "blockers": "bad_gaia",
        "cautions": "",
        "n_clean_epochs": 0,
        "minimum_m2_q16_solar": None,
    }
    flow = sequential_attrition(frame)
    assert flow.iloc[-1]["advanced"] == 3
