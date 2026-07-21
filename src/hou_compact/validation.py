"""Independent Gaia-orbit versus DESI-epoch validation summaries.

The functions in this module compare a fixed Gaia SB1 velocity curve with clean DESI
single-epoch radial velocities. Only one additive cross-survey velocity zero point is
fitted. No compact-object label or mass classification is produced here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from hou_compact.desi import clean_epoch_mask
from hou_compact.orbits import fit_systemic_velocity, gaia_sb1_velocity_shape
from hou_compact.physics import rv_pairwise_significance, rv_variability_chi2

_REQUIRED_GAIA_COLUMNS = {
    "solution_id",
    "source_id",
    "nss_solution_type",
    "gaia_ref_epoch",
    "period",
    "t_periastron",
    "eccentricity",
    "arg_periastron",
    "semi_amplitude_primary",
}
_REQUIRED_EPOCH_COLUMNS = {
    "source_id",
    "mjd",
    "vrad",
    "vrad_err",
    "success",
    "rvs_warn",
    "fiberstatus",
    "sn_b",
    "sn_r",
    "sn_z",
}


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing columns: {missing}")


def _optional_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def orbital_phase_coverage(mjd: Iterable[float], period_days: float, epoch_mjd: float) -> float:
    """Return circular phase coverage as one minus the largest unobserved phase gap."""
    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError("period_days must be finite and positive")
    if not math.isfinite(epoch_mjd):
        raise ValueError("epoch_mjd must be finite")
    times = np.asarray(list(mjd), dtype=float)
    if times.size == 0 or not np.all(np.isfinite(times)):
        raise ValueError("mjd must contain finite values")
    phases = np.unique(np.mod((times - epoch_mjd) / period_days, 1.0))
    if phases.size == 1:
        return 0.0
    gaps = np.diff(np.concatenate([phases, phases[:1] + 1.0]))
    return float(1.0 - np.max(gaps))


def score_orbit_consistency(
    gaia_rows: pd.DataFrame,
    epoch_rows: pd.DataFrame,
    *,
    min_clean_epochs: int = 2,
    min_arm_sn: float = 2.0,
    max_vrad_err: float = 20.0,
    jitter_kms: float = 0.0,
    exclude_programs: tuple[str, ...] = ("backup",),
) -> pd.DataFrame:
    """Score each Gaia orbital solution against independent DESI epoch velocities.

    Positive ``delta_chi2_constant_minus_orbit`` means the fixed Gaia orbit shape fits
    better than a constant-velocity model. Both models have one fitted additive velocity
    parameter, so the comparison does not reward the orbit model with extra free shape
    parameters. Rows with insufficient or invalid data are retained with a status code.
    """
    if min_clean_epochs < 2:
        raise ValueError("min_clean_epochs must be at least 2")
    _require_columns(gaia_rows, _REQUIRED_GAIA_COLUMNS, "gaia_rows")
    _require_columns(epoch_rows, _REQUIRED_EPOCH_COLUMNS, "epoch_rows")

    epochs = epoch_rows.copy()
    epochs["clean_epoch"] = clean_epoch_mask(
        epochs,
        min_arm_sn=min_arm_sn,
        max_vrad_err=max_vrad_err,
    )
    if exclude_programs and "program" in epochs.columns:
        epochs.loc[epochs["program"].isin(exclude_programs), "clean_epoch"] = False

    grouped = {int(source_id): group for source_id, group in epochs.groupby("source_id")}
    records: list[dict[str, object]] = []

    for _, gaia in gaia_rows.iterrows():
        source_id = int(gaia["source_id"])
        source_epochs = grouped.get(source_id, epochs.iloc[0:0])
        clean = source_epochs.loc[source_epochs["clean_epoch"]].sort_values(
            ["mjd"], kind="stable"
        )
        excluded_backup = 0
        if "program" in source_epochs.columns:
            excluded_backup = int(source_epochs["program"].isin(exclude_programs).sum())

        record: dict[str, object] = {
            "solution_id": gaia["solution_id"],
            "source_id": source_id,
            "nss_solution_type": gaia["nss_solution_type"],
            "n_raw_epochs": int(len(source_epochs)),
            "n_clean_epochs": int(len(clean)),
            "n_excluded_backup_epochs": excluded_backup,
            "status": "insufficient_clean_epochs",
            "error": "",
        }
        if len(clean) < min_clean_epochs:
            records.append(record)
            continue

        try:
            ref_epoch = float(gaia["gaia_ref_epoch"])
            period = float(gaia["period"])
            t_periastron = float(gaia["t_periastron"])
            semi_amplitude = float(gaia["semi_amplitude_primary"])
            eccentricity = _optional_float(gaia["eccentricity"])
            arg_periastron = _optional_float(gaia["arg_periastron"])

            mjd = clean["mjd"].to_numpy(dtype=float)
            velocity = clean["vrad"].to_numpy(dtype=float)
            error = clean["vrad_err"].to_numpy(dtype=float)
            shape = gaia_sb1_velocity_shape(
                mjd,
                ref_epoch_jyear=ref_epoch,
                period_days=period,
                t_periastron_days=t_periastron,
                eccentricity=eccentricity,
                arg_periastron_deg=arg_periastron,
                semi_amplitude_kms=semi_amplitude,
            )
            orbit_fit = fit_systemic_velocity(
                velocity,
                error,
                shape,
                jitter_kms=jitter_kms,
            )
            constant_chi2, constant_dof, constant_mean = rv_variability_chi2(
                velocity,
                np.sqrt(error**2 + jitter_kms**2),
            )
            periastron_mjd = float(
                mjd[0] - np.mod(mjd[0] - mjd[0], period)
            )
            # Coverage is origin-invariant; use the Gaia relative epoch convention here.
            phase_epoch = float(mjd[0] - np.mod(mjd[0], period))
            coverage = orbital_phase_coverage(mjd, period, phase_epoch)

            record.update(
                {
                    "status": "scored",
                    "baseline_days": float(np.max(mjd) - np.min(mjd)),
                    "phase_coverage": coverage,
                    "constant_weighted_mean_kms": constant_mean,
                    "constant_chi2": constant_chi2,
                    "constant_dof": constant_dof,
                    "constant_reduced_chi2": constant_chi2 / constant_dof,
                    "orbit_systemic_velocity_kms": orbit_fit.systemic_velocity_kms,
                    "orbit_chi2": orbit_fit.chi2,
                    "orbit_dof": orbit_fit.degrees_of_freedom,
                    "orbit_reduced_chi2": orbit_fit.reduced_chi2,
                    "delta_chi2_constant_minus_orbit": constant_chi2 - orbit_fit.chi2,
                    "max_pairwise_rv_significance": rv_pairwise_significance(
                        velocity, np.sqrt(error**2 + jitter_kms**2)
                    ),
                    "rms_orbit_residual_kms": float(
                        np.sqrt(np.mean(orbit_fit.residuals_kms**2))
                    ),
                    "periastron_epoch_placeholder_mjd": periastron_mjd,
                }
            )
            gaia_gamma = _optional_float(gaia.get("center_of_mass_velocity"))
            if gaia_gamma is not None:
                record["desi_minus_gaia_gamma_kms"] = (
                    orbit_fit.systemic_velocity_kms - gaia_gamma
                )
        except (TypeError, ValueError, RuntimeError, KeyError) as error_value:
            record["status"] = "model_error"
            record["error"] = f"{type(error_value).__name__}: {error_value}"
        records.append(record)

    result = pd.DataFrame.from_records(records)
    if not result.empty:
        result = result.sort_values(
            ["source_id", "solution_id"], kind="stable"
        ).reset_index(drop=True)
    return result
