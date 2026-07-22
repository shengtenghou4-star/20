"""Aggregate selection-bias diagnostics for primary-mass availability.

HOU-COMPACT must not silently treat the mass-scored subset as representative of the
full frozen Gaia cohort. These routines compare scored and unscored rows using only
candidate-safe aggregate statistics. They never rank or identify individual sources.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp


@dataclass(frozen=True)
class NumericSelectionAudit:
    """Aggregate distribution comparison for one numeric field."""

    field: str
    full_finite_count: int
    scored_finite_count: int
    unscored_finite_count: int
    scored_median: float | None
    unscored_median: float | None
    scored_q16: float | None
    scored_q84: float | None
    unscored_q16: float | None
    unscored_q84: float | None
    standardized_mean_difference: float | None
    ks_statistic: float | None
    ks_pvalue: float | None
    interpretation: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _finite_values(values: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    return numeric[np.isfinite(numeric)]


def _quantile(values: np.ndarray, probability: float) -> float | None:
    return float(np.quantile(values, probability)) if values.size else None


def _standardized_mean_difference(
    scored: np.ndarray,
    unscored: np.ndarray,
) -> float | None:
    if scored.size < 2 or unscored.size < 2:
        return None
    scored_variance = float(np.var(scored, ddof=1))
    unscored_variance = float(np.var(unscored, ddof=1))
    pooled = math.sqrt(0.5 * (scored_variance + unscored_variance))
    if not math.isfinite(pooled) or pooled == 0:
        return 0.0 if float(np.mean(scored)) == float(np.mean(unscored)) else None
    return float((np.mean(scored) - np.mean(unscored)) / pooled)


def audit_numeric_selection(
    frame: pd.DataFrame,
    *,
    field: str,
    scored_mask: pd.Series | np.ndarray,
) -> NumericSelectionAudit:
    """Compare one field between mass-scored and unscored rows."""
    if field not in frame.columns:
        raise KeyError(f"frame has no field {field!r}")
    mask = np.asarray(scored_mask, dtype=bool)
    if mask.ndim != 1 or mask.size != len(frame):
        raise ValueError("scored_mask must be one-dimensional and match frame length")
    scored = _finite_values(frame.loc[mask, field])
    unscored = _finite_values(frame.loc[~mask, field])
    full_count = int(np.isfinite(pd.to_numeric(frame[field], errors="coerce")).sum())
    smd = _standardized_mean_difference(scored, unscored)
    ks_statistic: float | None = None
    ks_pvalue: float | None = None
    if scored.size >= 2 and unscored.size >= 2:
        test = ks_2samp(scored, unscored, alternative="two-sided", method="auto")
        ks_statistic = float(test.statistic)
        ks_pvalue = float(test.pvalue)
    if scored.size == 0 or unscored.size == 0:
        interpretation = "insufficient_two_group_coverage"
    elif smd is not None and abs(smd) >= 0.8:
        interpretation = "large_distribution_shift"
    elif smd is not None and abs(smd) >= 0.5:
        interpretation = "moderate_distribution_shift"
    elif smd is not None and abs(smd) >= 0.2:
        interpretation = "small_distribution_shift"
    else:
        interpretation = "minimal_standardized_shift"
    return NumericSelectionAudit(
        field=field,
        full_finite_count=full_count,
        scored_finite_count=int(scored.size),
        unscored_finite_count=int(unscored.size),
        scored_median=_quantile(scored, 0.5),
        unscored_median=_quantile(unscored, 0.5),
        scored_q16=_quantile(scored, 0.16),
        scored_q84=_quantile(scored, 0.84),
        unscored_q16=_quantile(unscored, 0.16),
        unscored_q84=_quantile(unscored, 0.84),
        standardized_mean_difference=smd,
        ks_statistic=ks_statistic,
        ks_pvalue=ks_pvalue,
        interpretation=interpretation,
    )


def quantile_bin_selection_rates(
    frame: pd.DataFrame,
    *,
    field: str,
    scored_mask: pd.Series | np.ndarray,
    quantiles: Iterable[float] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
) -> pd.DataFrame:
    """Return candidate-safe scored fractions across empirical field bins."""
    if field not in frame.columns:
        raise KeyError(f"frame has no field {field!r}")
    mask = np.asarray(scored_mask, dtype=bool)
    if mask.ndim != 1 or mask.size != len(frame):
        raise ValueError("scored_mask must be one-dimensional and match frame length")
    probabilities = np.asarray(tuple(quantiles), dtype=float)
    if (
        probabilities.ndim != 1
        or probabilities.size < 2
        or not np.all(np.isfinite(probabilities))
        or probabilities[0] != 0
        or probabilities[-1] != 1
        or np.any(np.diff(probabilities) <= 0)
    ):
        raise ValueError("quantiles must be strictly increasing from 0 to 1")
    values = pd.to_numeric(frame[field], errors="coerce")
    finite = np.isfinite(values.to_numpy(dtype=float))
    if int(np.sum(finite)) < 2:
        return pd.DataFrame(
            columns=[
                "field",
                "bin_index",
                "lower",
                "upper",
                "rows",
                "scored_rows",
                "scored_fraction",
            ]
        )
    finite_values = values.loc[finite].to_numpy(dtype=float)
    edges = np.quantile(finite_values, probabilities)
    edges = np.unique(edges)
    if edges.size < 2:
        edges = np.asarray([float(finite_values[0]), float(finite_values[0])])
    records: list[dict[str, object]] = []
    for index in range(edges.size - 1):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        if index == edges.size - 2:
            in_bin = finite & values.ge(lower) & values.le(upper)
        else:
            in_bin = finite & values.ge(lower) & values.lt(upper)
        rows = int(np.sum(in_bin))
        scored_rows = int(np.sum(mask & np.asarray(in_bin, dtype=bool)))
        records.append(
            {
                "field": field,
                "bin_index": index,
                "lower": lower,
                "upper": upper,
                "rows": rows,
                "scored_rows": scored_rows,
                "scored_fraction": scored_rows / rows if rows else None,
            }
        )
    return pd.DataFrame.from_records(records)


def primary_mass_status_mask(primary: pd.DataFrame) -> pd.Series:
    """Return the frozen definition of a usable primary-mass product."""
    if "status" not in primary.columns:
        raise KeyError("primary table has no status column")
    return primary["status"].astype(str).isin({"scored", "weak_prior"})
