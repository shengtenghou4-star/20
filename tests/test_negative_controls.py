import numpy as np
import pandas as pd

from hou_compact.negative_controls import (
    OrbitScoreThresholds,
    add_deterministic_source_offsets,
    aggregate_orbit_score_counts,
    audit_systemic_offset_invariance,
    phase_scramble_gaia_rows,
    run_phase_scramble_control,
)
from hou_compact.orbits import gaia_periastron_mjd, sb1_velocity_shape


def _gaia() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "solution_id": [1],
            "source_id": [123],
            "nss_solution_type": ["SB1"],
            "gaia_ref_epoch": [2016.0],
            "period": [10.0],
            "t_periastron": [0.0],
            "eccentricity": [0.0],
            "arg_periastron": [0.0],
            "semi_amplitude_primary": [20.0],
            "center_of_mass_velocity": [30.0],
        }
    )


def _epochs() -> pd.DataFrame:
    epoch = gaia_periastron_mjd(2016.0, 0.0)
    mjd = epoch + np.array([0.0, 2.5, 5.0, 7.5])
    shape = sb1_velocity_shape(
        mjd,
        period_days=10.0,
        periastron_mjd=epoch,
        eccentricity=0.0,
        arg_periastron_deg=0.0,
        semi_amplitude_kms=20.0,
    )
    return pd.DataFrame(
        {
            "source_id": [123] * 4,
            "mjd": mjd,
            "vrad": shape + 30.0,
            "vrad_err": [1.0] * 4,
            "success": [True] * 4,
            "rvs_warn": [0] * 4,
            "fiberstatus": [0] * 4,
            "sn_b": [5.0] * 4,
            "sn_r": [5.0] * 4,
            "sn_z": [5.0] * 4,
            "program": ["bright"] * 4,
        }
    )


def test_phase_scramble_is_deterministic_and_changes_phase() -> None:
    first = phase_scramble_gaia_rows(_gaia(), repetition=3)
    second = phase_scramble_gaia_rows(_gaia(), repetition=3)
    other = phase_scramble_gaia_rows(_gaia(), repetition=4)
    assert first["t_periastron"].tolist() == second["t_periastron"].tolist()
    assert first.iloc[0]["t_periastron"] != 0.0
    assert first.iloc[0]["t_periastron"] != other.iloc[0]["t_periastron"]
    assert 0.0 <= first.iloc[0]["t_periastron"] < 10.0


def test_source_offsets_are_constant_within_source() -> None:
    epochs = _epochs()
    shifted = add_deterministic_source_offsets(epochs)
    differences = (shifted["vrad"] - epochs["vrad"]).to_numpy(dtype=float)
    assert np.ptp(differences) < 1e-12
    assert differences[0] != 0.0


def test_observed_orbit_passes_aggregate_thresholds() -> None:
    from hou_compact.validation import score_orbit_consistency

    scores = score_orbit_consistency(_gaia(), _epochs(), min_clean_epochs=2)
    counts = aggregate_orbit_score_counts(
        scores,
        OrbitScoreThresholds(minimum_clean_visits=3),
    )
    assert counts["scored_rows"] == 1
    assert counts["eligible_absolute_fit_rows"] == 1
    assert counts["delta_chi2_counts"]["ge_16"] == 1


def test_phase_scramble_returns_aggregate_only_null() -> None:
    null, summary = run_phase_scramble_control(
        _gaia(),
        _epochs(),
        repetitions=8,
        thresholds=OrbitScoreThresholds(minimum_clean_visits=3),
    )
    assert len(null) == 8
    assert "source_id" not in null.columns
    assert summary["candidate_safe"] is True
    assert summary["repetitions"] == 8
    assert summary["observed"]["delta_chi2_counts"]["ge_16"] == 1


def test_systemic_offset_invariance_passes() -> None:
    audit = audit_systemic_offset_invariance(_gaia(), _epochs(), tolerance=1e-8)
    assert audit["status"] == "pass"
    assert audit["comparable_scored_rows"] == 1
    assert audit["values_above_tolerance"] == 0
