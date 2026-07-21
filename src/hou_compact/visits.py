"""Construct statistically independent DESI radial-velocity visits.

Multiple DESI exposures obtained close together are not independent orbital phase
samples. This module groups nearby clean exposures into visits, combines them by inverse
variance, and inflates the visit uncertainty when the exposures scatter more than their
reported errors predict.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

_REQUIRED_COLUMNS = {"source_id", "mjd", "vrad", "vrad_err"}


def _require_columns(rows: pd.DataFrame) -> None:
    missing = sorted(_REQUIRED_COLUMNS - set(rows.columns))
    if missing:
        raise KeyError(f"rows are missing columns: {missing}")


def _join_unique(values: pd.Series) -> str:
    clean = sorted({str(value) for value in values if pd.notna(value) and str(value)})
    return ";".join(clean)


def aggregate_independent_visits(
    rows: pd.DataFrame,
    *,
    maximum_gap_hours: float = 2.0,
    error_floor_kms: float = 0.0,
) -> pd.DataFrame:
    """Aggregate temporally adjacent exposures into independent RV visits.

    A new visit begins whenever the source changes, the Gaia/DESI ``night`` value changes
    when available, or the gap from the previous exposure exceeds ``maximum_gap_hours``.
    The visit RV and MJD are inverse-variance weighted. For visits with multiple
    exposures, the formal error is multiplied by ``sqrt(max(1, chi2/(n-1)))`` so
    underestimated errors or short-timescale disagreement are retained rather than
    averaged away. ``error_floor_kms`` is then added in quadrature.
    """
    _require_columns(rows)
    if not math.isfinite(maximum_gap_hours) or maximum_gap_hours <= 0:
        raise ValueError("maximum_gap_hours must be finite and positive")
    if not math.isfinite(error_floor_kms) or error_floor_kms < 0:
        raise ValueError("error_floor_kms must be finite and non-negative")
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "source_id",
                "visit_id",
                "mjd",
                "vrad",
                "vrad_err",
                "n_exposures",
                "visit_span_hours",
                "within_visit_chi2",
                "within_visit_dof",
                "within_visit_reduced_chi2",
                "formal_mean_error_kms",
                "error_inflation_factor",
                "night",
                "survey",
                "program",
            ]
        )

    frame = rows.copy()
    numeric = frame[["mjd", "vrad", "vrad_err"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.all(np.isfinite(numeric.to_numpy())):
        raise ValueError("mjd, vrad, and vrad_err must be finite numeric values")
    if np.any(numeric["vrad_err"].to_numpy() <= 0):
        raise ValueError("vrad_err values must be positive")
    frame[["mjd", "vrad", "vrad_err"]] = numeric
    frame = frame.sort_values(["source_id", "mjd"], kind="stable").reset_index(drop=True)

    max_gap_days = maximum_gap_hours / 24.0
    source_change = frame["source_id"].ne(frame["source_id"].shift())
    time_gap = frame["mjd"].sub(frame["mjd"].shift()).gt(max_gap_days)
    if "night" in frame.columns:
        night_change = frame["night"].ne(frame["night"].shift())
        night_change = night_change & frame["night"].notna() & frame["night"].shift().notna()
    else:
        night_change = pd.Series(False, index=frame.index)
    new_visit = source_change | time_gap | night_change
    frame["_visit_number"] = new_visit.groupby(frame["source_id"]).cumsum().astype(int) - 1

    records: list[dict[str, object]] = []
    for (source_id, visit_number), group in frame.groupby(
        ["source_id", "_visit_number"], sort=False
    ):
        velocity = group["vrad"].to_numpy(dtype=float)
        error = group["vrad_err"].to_numpy(dtype=float)
        mjd = group["mjd"].to_numpy(dtype=float)
        weights = 1.0 / error**2
        weight_sum = float(np.sum(weights))
        mean_velocity = float(np.sum(weights * velocity) / weight_sum)
        mean_mjd = float(np.sum(weights * mjd) / weight_sum)
        formal_error = math.sqrt(1.0 / weight_sum)
        count = len(group)
        if count > 1:
            chi2 = float(np.sum(((velocity - mean_velocity) / error) ** 2))
            dof = count - 1
            reduced = chi2 / dof
            inflation = math.sqrt(max(1.0, reduced))
        else:
            chi2 = 0.0
            dof = 0
            reduced = math.nan
            inflation = 1.0
        inflated_error = formal_error * inflation
        final_error = math.sqrt(inflated_error**2 + error_floor_kms**2)
        record: dict[str, object] = {
            "source_id": int(source_id),
            "visit_id": f"{int(source_id)}:{int(visit_number)}",
            "mjd": mean_mjd,
            "vrad": mean_velocity,
            "vrad_err": final_error,
            "n_exposures": count,
            "visit_span_hours": float((np.max(mjd) - np.min(mjd)) * 24.0),
            "within_visit_chi2": chi2,
            "within_visit_dof": dof,
            "within_visit_reduced_chi2": reduced,
            "formal_mean_error_kms": formal_error,
            "error_inflation_factor": inflation,
        }
        if "night" in group.columns:
            nights = [value for value in group["night"] if pd.notna(value)]
            record["night"] = nights[0] if nights else None
        else:
            record["night"] = None
        record["survey"] = _join_unique(group["survey"]) if "survey" in group else ""
        record["program"] = _join_unique(group["program"]) if "program" in group else ""
        records.append(record)

    result = pd.DataFrame.from_records(records)
    return result.sort_values(["source_id", "mjd"], kind="stable").reset_index(drop=True)
