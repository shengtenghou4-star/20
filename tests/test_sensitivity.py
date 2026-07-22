import pandas as pd
import pytest

from hou_compact.sensitivity import (
    SensitivityGrid,
    candidate_safe_sensitivity_summary,
    iter_sensitivity_configs,
    run_triage_sensitivity,
)


def _row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "significance": 10.0,
        "conf_spectro_period": 0.999,
        "rv_n_good_obs_primary": 20,
        "flags": 0,
        "orbit_status": "scored",
        "n_clean_epochs": 4,
        "phase_coverage": 0.4,
        "delta_chi2_constant_minus_orbit": 20.0,
        "orbit_reduced_chi2": 1.0,
        "primary_status": "scored",
        "fractional_68_width": 0.4,
        "mass_status": "scored",
        "minimum_m2_q16_solar": 4.0,
        "minimum_m2_q50_solar": 5.0,
        "gaia_contamination_high_risk_count": 0,
        "gaia_contamination_caution_count": 0,
        "gaia_contamination_context_count": 0,
        "roche_status": "detached_geometry_consistent",
        "filling_q16": 0.2,
        "filling_q50": 0.3,
        "nss_solution_type": "SB1",
        "source_match_mode": "official_datalab_zpix_targetid",
    }
    row.update(updates)
    return row


def _frame() -> pd.DataFrame:
    robust = _row()
    marginal = _row(
        n_clean_epochs=2,
        phase_coverage=0.15,
        delta_chi2_constant_minus_orbit=5.0,
        fractional_68_width=0.8,
        minimum_m2_q16_solar=2.0,
        minimum_m2_q50_solar=2.5,
        nss_solution_type="SB1C",
        source_match_mode="gaia_dr2_neighbourhood_refid",
    )
    gaia_hold = _row(significance=2.0)
    frame = pd.DataFrame([robust, marginal, gaia_hold])
    frame.index = [10, 20, 30]
    return frame


def test_grid_size_and_unique_configs() -> None:
    grid = SensitivityGrid(
        min_clean_desi_epochs=(2, 3),
        min_phase_coverage=(0.1, 0.2),
        min_delta_chi2=(4.0, 9.0),
        max_primary_fractional_width=(0.5, 1.0),
    )
    configs = iter_sensitivity_configs(grid)
    assert grid.size == 16
    assert len(configs) == 16
    assert len({repr(config) for config in configs}) == 16


def test_sensitivity_range_captures_marginal_row() -> None:
    grid = SensitivityGrid(
        min_clean_desi_epochs=(2, 3),
        min_phase_coverage=(0.1, 0.2),
        min_delta_chi2=(4.0, 9.0),
        max_primary_fractional_width=(0.5, 1.0),
    )
    results = run_triage_sensitivity(_frame(), grid=grid)
    assert len(results) == 16
    assert results["all_evidence_gates_passed"].min() == 1
    assert results["all_evidence_gates_passed"].max() == 2
    assert results["gaia_quality_hold"].eq(1).all()
    assert results["config_id"].is_unique


def test_strata_remain_aggregate_and_index_safe() -> None:
    grid = SensitivityGrid(
        min_clean_desi_epochs=(2,),
        min_phase_coverage=(0.1,),
        min_delta_chi2=(4.0,),
        max_primary_fractional_width=(1.0,),
    )
    row = run_triage_sensitivity(_frame(), grid=grid).iloc[0]
    assert row["sb1_strata"]["SB1"]["cohort_rows"] == 2
    assert row["sb1_strata"]["SB1C"]["all_evidence_gates_passed"] == 1
    assert row["identifier_path_strata"][
        "gaia_dr2_neighbourhood_refid"
    ]["all_evidence_gates_passed"] == 1


def test_candidate_safe_summary_reports_ranges() -> None:
    grid = SensitivityGrid(
        min_clean_desi_epochs=(2, 3),
        min_phase_coverage=(0.1,),
        min_delta_chi2=(4.0,),
        max_primary_fractional_width=(1.0,),
    )
    results = run_triage_sensitivity(_frame(), grid=grid)
    summary = candidate_safe_sensitivity_summary(results)
    assert summary["candidate_safe"] is True
    assert summary["configuration_count"] == 2
    assert summary["all_evidence_gates_passed_range"] == {
        "minimum": 1,
        "maximum": 2,
    }
    assert "source_id" not in summary


def test_invalid_unsorted_grid_fails_closed() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        SensitivityGrid(min_delta_chi2=(9.0, 4.0))


def test_empty_input_fails_closed() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        run_triage_sensitivity(pd.DataFrame())
