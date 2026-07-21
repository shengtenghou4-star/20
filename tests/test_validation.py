import numpy as np
import pandas as pd

from hou_compact.orbits import gaia_periastron_mjd, sb1_velocity_shape
from hou_compact.validation import orbital_phase_coverage, score_orbit_consistency


def _gaia_row() -> pd.DataFrame:
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


def _epoch_rows(program: str = "bright") -> pd.DataFrame:
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
            "program": [program] * 4,
        }
    )


def test_phase_coverage_for_quadrature_sampling() -> None:
    assert orbital_phase_coverage([0.0, 2.5, 5.0, 7.5], 10.0, 0.0) == 0.75


def test_fixed_gaia_orbit_beats_constant_velocity() -> None:
    result = score_orbit_consistency(_gaia_row(), _epoch_rows())
    row = result.iloc[0]
    assert row["status"] == "scored"
    assert row["n_clean_epochs"] == 4
    assert row["orbit_chi2"] < 1e-18
    assert row["delta_chi2_constant_minus_orbit"] > 700.0
    assert abs(row["orbit_systemic_velocity_kms"] - 30.0) < 1e-10
    assert abs(row["phase_coverage"] - 0.75) < 1e-12


def test_backup_epochs_are_excluded_by_default() -> None:
    result = score_orbit_consistency(_gaia_row(), _epoch_rows(program="backup"))
    row = result.iloc[0]
    assert row["status"] == "insufficient_clean_epochs"
    assert row["n_clean_epochs"] == 0
    assert row["n_excluded_backup_epochs"] == 4
