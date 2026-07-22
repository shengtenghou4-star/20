"""Candidate-safe coverage diagnostics for Dark-668 external RV data.

This module intentionally works before per-spectrum uncertainty acquisition.  It
summarizes cadence, baseline, phase coverage relative to the published period
summary, and raw velocity spread.  These diagnostics decide where uncertainty-
aware extraction effort should be spent; they are not likelihood scores and must
not be interpreted as binary or compact-object evidence.
"""

from __future__ import annotations

from typing import Any
import math

import numpy as np
import pandas as pd

from hou_compact.validation import orbital_phase_coverage

_REQUIRED_CANDIDATE_COLUMNS = {"source_id", "fit_period"}
_REQUIRED_EPOCH_COLUMNS = {"source_id", "mjd", "vrad"}


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing columns: {missing}")


def _finite_positive(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _robust_velocity_amplitude(velocity: np.ndarray) -> float:
    if velocity.size == 0:
        return math.nan
    if velocity.size < 5:
        return float(np.max(velocity) - np.min(velocity))
    lower, upper = np.quantile(velocity, [0.05, 0.95])
    return float(upper - lower)


def summarize_period_coverage(
    candidates: pd.DataFrame,
    epoch_rows: pd.DataFrame,
) -> pd.DataFrame:
    """Return one source-level coverage row per candidate without classification."""

    _require_columns(candidates, _REQUIRED_CANDIDATE_COLUMNS, "candidates")
    _require_columns(epoch_rows, _REQUIRED_EPOCH_COLUMNS, "epoch_rows")
    candidate_ids = pd.to_numeric(candidates["source_id"], errors="raise").astype("int64")
    if candidate_ids.duplicated().any():
        raise ValueError("candidates contain duplicate source_id rows")

    epochs = epoch_rows.copy()
    epochs["source_id"] = pd.to_numeric(epochs["source_id"], errors="raise").astype("int64")
    epochs["mjd"] = pd.to_numeric(epochs["mjd"], errors="coerce")
    epochs["vrad"] = pd.to_numeric(epochs["vrad"], errors="coerce")
    grouped = {int(key): value for key, value in epochs.groupby("source_id", sort=False)}

    records: list[dict[str, Any]] = []
    prepared = candidates.assign(source_id=candidate_ids)
    for candidate in prepared.itertuples(index=False):
        source_id = int(candidate.source_id)
        period = _finite_positive(getattr(candidate, "fit_period"))
        source_epochs = grouped.get(source_id, epochs.iloc[0:0]).copy()
        finite = np.isfinite(source_epochs["mjd"]) & np.isfinite(source_epochs["vrad"])
        usable = source_epochs.loc[finite].sort_values("mjd", kind="stable")
        record: dict[str, Any] = {
            "source_id": source_id,
            "status": "no_usable_epochs",
            "published_period_days": period,
            "n_raw_epoch_rows": int(len(source_epochs)),
            "n_usable_epochs": int(len(usable)),
        }
        for optional in ("population", "priority_rank", "followup_score"):
            if hasattr(candidate, optional):
                record[optional] = getattr(candidate, optional)
        if usable.empty:
            records.append(record)
            continue

        mjd = usable["mjd"].to_numpy(dtype=float)
        velocity = usable["vrad"].to_numpy(dtype=float)
        baseline = float(np.max(mjd) - np.min(mjd))
        median = float(np.median(velocity))
        mad = float(1.4826 * np.median(np.abs(velocity - median)))
        record.update(
            {
                "status": "single_usable_epoch" if len(usable) == 1 else "coverage_summarized",
                "n_unique_mjd_days": int(pd.Series(np.floor(mjd)).nunique()),
                "baseline_days": baseline,
                "rv_min_kms": float(np.min(velocity)),
                "rv_max_kms": float(np.max(velocity)),
                "rv_range_kms": float(np.max(velocity) - np.min(velocity)),
                "rv_robust_amplitude_kms": _robust_velocity_amplitude(velocity),
                "rv_median_kms": median,
                "rv_mad_sigma_kms": mad,
            }
        )
        if period is not None:
            record["period_cycles_spanned"] = baseline / period
            record["phase_coverage"] = (
                orbital_phase_coverage(mjd, period, float(mjd[0]))
                if len(usable) >= 2
                else 0.0
            )
        records.append(record)

    result = pd.DataFrame.from_records(records)
    if not result.empty:
        result = result.sort_values("source_id", kind="stable").reset_index(drop=True)
    return result


def candidate_safe_coverage_summary(coverage: pd.DataFrame) -> dict[str, Any]:
    """Aggregate a source-level coverage table without emitting identifiers."""

    status = coverage.get("status", pd.Series(dtype=str))
    usable = pd.to_numeric(
        coverage.get("n_usable_epochs", pd.Series(dtype=float)), errors="coerce"
    )
    cycles = pd.to_numeric(
        coverage.get("period_cycles_spanned", pd.Series(dtype=float)), errors="coerce"
    )
    phase = pd.to_numeric(
        coverage.get("phase_coverage", pd.Series(dtype=float)), errors="coerce"
    )
    amplitude = pd.to_numeric(
        coverage.get("rv_robust_amplitude_kms", pd.Series(dtype=float)), errors="coerce"
    )
    payload: dict[str, Any] = {
        "candidate_rows": int(len(coverage)),
        "status_counts": {
            str(key): int(value) for key, value in status.value_counts().items()
        },
        "usable_epoch_threshold_counts": {
            "ge_2": int(usable.ge(2).sum()),
            "ge_3": int(usable.ge(3).sum()),
            "ge_5": int(usable.ge(5).sum()),
            "ge_10": int(usable.ge(10).sum()),
        },
        "period_cycles_threshold_counts": {
            "ge_0.5": int(cycles.ge(0.5).sum()),
            "ge_1": int(cycles.ge(1.0).sum()),
            "ge_2": int(cycles.ge(2.0).sum()),
        },
        "phase_coverage_threshold_counts": {
            "ge_0.2": int(phase.ge(0.2).sum()),
            "ge_0.4": int(phase.ge(0.4).sum()),
            "ge_0.6": int(phase.ge(0.6).sum()),
        },
        "raw_amplitude_threshold_counts": {
            "ge_10_kms": int(amplitude.ge(10.0).sum()),
            "ge_20_kms": int(amplitude.ge(20.0).sum()),
            "ge_50_kms": int(amplitude.ge(50.0).sum()),
        },
        "claim_boundary": (
            "Cadence and raw-spread diagnostics only. The multiple-epoch summary lacks "
            "per-spectrum uncertainties, so no likelihood, orbit, binary, or compact-object "
            "claim is authorized."
        ),
    }
    if "population" in coverage.columns:
        payload["population_coverage_counts"] = {
            str(key): int(value)
            for key, value in coverage.loc[usable.ge(1), "population"]
            .value_counts()
            .sort_index()
            .items()
        }
    return payload
