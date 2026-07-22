"""Period-prior radial-velocity triage for Dark-668 candidates.

The Dark-668 catalogues contain posterior summaries for period and companion mass,
not published orbital phase or eccentricity solutions.  This module therefore does
*not* reuse the fixed-Gaia-orbit validator.  Instead it asks a narrower question:
do independent multi-visit radial velocities show coherent circular-orbit-like
variation at a period compatible with the published period posterior?

The result is a follow-up statistic, never a compact-object classification.  A
circular sinusoid is deliberately used as a conservative, reproducible first gate;
full Keplerian inference, luminous-companion rejection, and novelty review remain
separate downstream requirements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2 as chi2_distribution

from hou_compact.desi import clean_epoch_mask
from hou_compact.physics import rv_pairwise_significance
from hou_compact.validation import orbital_phase_coverage
from hou_compact.visits import aggregate_independent_visits

_REQUIRED_CANDIDATE_COLUMNS = {
    "source_id",
    "fit_period",
    "fit_period_errup",
    "fit_period_errlow",
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


@dataclass(frozen=True)
class PeriodPriorConfig:
    """Frozen settings for first-pass period-prior RV triage."""

    minimum_independent_visits: int = 5
    period_grid_size: int = 192
    posterior_sigma_span: float = 3.0
    fallback_period_factor: float = 2.0
    minimum_period_days: float = 0.25
    maximum_period_days: float = 50_000.0
    minimum_arm_sn: float = 2.0
    maximum_vrad_error_kms: float = 20.0
    jitter_kms: float = 0.0
    aggregate_visits: bool = True
    maximum_visit_gap_hours: float = 2.0
    visit_error_floor_kms: float = 0.0
    permutation_repetitions: int = 100
    base_seed: int = 20260723

    def __post_init__(self) -> None:
        if self.minimum_independent_visits < 4:
            raise ValueError("minimum_independent_visits must be at least 4")
        if self.period_grid_size < 16:
            raise ValueError("period_grid_size must be at least 16")
        if not math.isfinite(self.posterior_sigma_span) or self.posterior_sigma_span <= 0:
            raise ValueError("posterior_sigma_span must be finite and positive")
        if not math.isfinite(self.fallback_period_factor) or self.fallback_period_factor <= 1:
            raise ValueError("fallback_period_factor must be greater than one")
        if not math.isfinite(self.minimum_period_days) or self.minimum_period_days <= 0:
            raise ValueError("minimum_period_days must be finite and positive")
        if (
            not math.isfinite(self.maximum_period_days)
            or self.maximum_period_days <= self.minimum_period_days
        ):
            raise ValueError("maximum_period_days must exceed minimum_period_days")
        if not math.isfinite(self.minimum_arm_sn) or self.minimum_arm_sn < 0:
            raise ValueError("minimum_arm_sn must be finite and non-negative")
        if (
            not math.isfinite(self.maximum_vrad_error_kms)
            or self.maximum_vrad_error_kms <= 0
        ):
            raise ValueError("maximum_vrad_error_kms must be finite and positive")
        if not math.isfinite(self.jitter_kms) or self.jitter_kms < 0:
            raise ValueError("jitter_kms must be finite and non-negative")
        if not isinstance(self.aggregate_visits, bool):
            raise TypeError("aggregate_visits must be boolean")
        if (
            not math.isfinite(self.maximum_visit_gap_hours)
            or self.maximum_visit_gap_hours <= 0
        ):
            raise ValueError("maximum_visit_gap_hours must be finite and positive")
        if (
            not math.isfinite(self.visit_error_floor_kms)
            or self.visit_error_floor_kms < 0
        ):
            raise ValueError("visit_error_floor_kms must be finite and non-negative")
        if self.permutation_repetitions < 0:
            raise ValueError("permutation_repetitions must be non-negative")

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeightedLinearFit:
    chi2: float
    dof: int
    coefficients: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]

    @property
    def reduced_chi2(self) -> float:
        return self.chi2 / self.dof if self.dof > 0 else math.nan


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


def _weighted_linear_fit(
    design: np.ndarray,
    velocity: np.ndarray,
    error: np.ndarray,
) -> WeightedLinearFit:
    if design.ndim != 2:
        raise ValueError("design must be two-dimensional")
    if velocity.ndim != 1 or error.ndim != 1:
        raise ValueError("velocity and error must be one-dimensional")
    if len(velocity) != design.shape[0] or len(error) != design.shape[0]:
        raise ValueError("design, velocity, and error lengths are inconsistent")
    if design.shape[0] <= design.shape[1]:
        raise ValueError("fit requires more observations than free coefficients")
    if not np.all(np.isfinite(design)) or not np.all(np.isfinite(velocity)):
        raise ValueError("design and velocity must be finite")
    if not np.all(np.isfinite(error)) or np.any(error <= 0):
        raise ValueError("error must contain finite positive values")

    weighted_design = design / error[:, None]
    weighted_velocity = velocity / error
    coefficients, _, rank, _ = np.linalg.lstsq(
        weighted_design,
        weighted_velocity,
        rcond=None,
    )
    if rank != design.shape[1]:
        raise ValueError("weighted design matrix is rank deficient")
    normal = weighted_design.T @ weighted_design
    covariance = np.linalg.inv(normal)
    residual = (velocity - design @ coefficients) / error
    chi2 = float(residual @ residual)
    dof = int(design.shape[0] - design.shape[1])
    return WeightedLinearFit(
        chi2=chi2,
        dof=dof,
        coefficients=tuple(float(value) for value in coefficients),
        covariance=tuple(
            tuple(float(value) for value in row) for row in covariance
        ),
    )


def fit_constant_velocity(
    velocity: np.ndarray,
    error: np.ndarray,
) -> WeightedLinearFit:
    design = np.ones((len(velocity), 1), dtype=float)
    return _weighted_linear_fit(design, velocity, error)


def fit_circular_velocity(
    mjd: np.ndarray,
    velocity: np.ndarray,
    error: np.ndarray,
    period_days: float,
) -> WeightedLinearFit:
    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError("period_days must be finite and positive")
    origin = float(np.min(mjd))
    angle = 2.0 * np.pi * (mjd - origin) / period_days
    design = np.column_stack(
        [
            np.ones(len(mjd), dtype=float),
            np.sin(angle),
            np.cos(angle),
        ]
    )
    return _weighted_linear_fit(design, velocity, error)


def period_prior_grid(
    period_days: object,
    error_up_days: object,
    error_low_days: object,
    config: PeriodPriorConfig = PeriodPriorConfig(),
) -> np.ndarray:
    """Construct a deterministic grid from the published asymmetric period summary."""

    period = _finite_positive(period_days)
    if period is None:
        raise ValueError("fit_period must be finite and positive")
    error_up = _finite_positive(error_up_days)
    error_low = _finite_positive(error_low_days)
    if error_up is not None and error_low is not None:
        lower = period - config.posterior_sigma_span * error_low
        upper = period + config.posterior_sigma_span * error_up
    else:
        lower = period / config.fallback_period_factor
        upper = period * config.fallback_period_factor
    lower = max(config.minimum_period_days, lower)
    upper = min(config.maximum_period_days, upper)
    if not math.isfinite(lower) or not math.isfinite(upper) or upper <= lower:
        lower = max(config.minimum_period_days, period / config.fallback_period_factor)
        upper = min(config.maximum_period_days, period * config.fallback_period_factor)
    if upper <= lower:
        raise ValueError("period prior collapses after configured bounds")
    grid = np.geomspace(lower, upper, config.period_grid_size)
    grid = np.unique(np.concatenate([grid, np.asarray([period], dtype=float)]))
    return np.sort(grid)


def _bic(chi2: float, free_parameters: int, observations: int) -> float:
    if observations <= free_parameters:
        return math.inf
    return float(chi2 + free_parameters * math.log(observations))


def scan_period_prior(
    mjd: np.ndarray,
    velocity: np.ndarray,
    error: np.ndarray,
    periods: np.ndarray,
) -> dict[str, float]:
    """Return the best circular fit across a frozen period grid."""

    constant = fit_constant_velocity(velocity, error)
    constant_bic = _bic(constant.chi2, 1, len(mjd))
    best: dict[str, float] | None = None
    for period in periods:
        fit = fit_circular_velocity(mjd, velocity, error, float(period))
        # The selected period is counted as one additional effective parameter.
        periodic_bic = _bic(fit.chi2, 4, len(mjd))
        gamma, sine_coefficient, cosine_coefficient = fit.coefficients
        amplitude = math.hypot(sine_coefficient, cosine_coefficient)
        phase_radians = math.atan2(cosine_coefficient, sine_coefficient)
        record = {
            "best_period_days": float(period),
            "periodic_chi2": fit.chi2,
            "periodic_dof": float(fit.dof),
            "periodic_reduced_chi2": fit.reduced_chi2,
            "periodic_bic": periodic_bic,
            "systemic_velocity_kms": gamma,
            "semi_amplitude_proxy_kms": amplitude,
            "phase_radians_at_min_mjd": phase_radians,
        }
        if best is None or record["periodic_bic"] < best["periodic_bic"]:
            best = record
    if best is None:
        raise RuntimeError("period grid produced no fits")
    best.update(
        {
            "constant_chi2": constant.chi2,
            "constant_dof": float(constant.dof),
            "constant_reduced_chi2": constant.reduced_chi2,
            "constant_bic": constant_bic,
            "delta_chi2_constant_minus_periodic": (
                constant.chi2 - best["periodic_chi2"]
            ),
            "delta_bic_constant_minus_periodic": (
                constant_bic - best["periodic_bic"]
            ),
        }
    )
    return best


def deterministic_source_seed(source_id: int, base_seed: int, label: str) -> int:
    payload = f"{base_seed}|{source_id}|{label}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def permutation_false_alarm_probability(
    mjd: np.ndarray,
    velocity: np.ndarray,
    error: np.ndarray,
    periods: np.ndarray,
    observed_delta_bic: float,
    *,
    source_id: int,
    repetitions: int,
    base_seed: int,
) -> tuple[float, float, float]:
    """Estimate a deterministic within-source temporal-coherence false-alarm rate."""

    if repetitions == 0:
        return math.nan, math.nan, math.nan
    generator = np.random.default_rng(
        deterministic_source_seed(source_id, base_seed, "period_prior_permutation")
    )
    null_scores = np.empty(repetitions, dtype=float)
    indices = np.arange(len(mjd))
    for repetition in range(repetitions):
        permutation = generator.permutation(indices)
        null = scan_period_prior(
            mjd,
            velocity[permutation],
            error[permutation],
            periods,
        )
        null_scores[repetition] = null["delta_bic_constant_minus_periodic"]
    exceed = int(np.sum(null_scores >= observed_delta_bic))
    probability = (exceed + 1.0) / (repetitions + 1.0)
    return (
        float(probability),
        float(np.median(null_scores)),
        float(np.max(null_scores)),
    )


def _prepare_analysis_visits(
    source_epochs: pd.DataFrame,
    config: PeriodPriorConfig,
) -> tuple[pd.DataFrame, int]:
    clean_mask = clean_epoch_mask(
        source_epochs,
        min_arm_sn=config.minimum_arm_sn,
        max_vrad_err=config.maximum_vrad_error_kms,
    )
    clean = source_epochs.loc[clean_mask].sort_values("mjd", kind="stable")
    if config.aggregate_visits and not clean.empty:
        visits = aggregate_independent_visits(
            clean,
            maximum_gap_hours=config.maximum_visit_gap_hours,
            error_floor_kms=config.visit_error_floor_kms,
        )
    else:
        visits = clean.loc[:, ["source_id", "mjd", "vrad", "vrad_err"]].copy()
        if not visits.empty:
            visits["n_exposures"] = 1
            visits["visit_span_hours"] = 0.0
            visits["error_inflation_factor"] = 1.0
    return visits, int(len(clean))


def score_period_prior_candidates(
    candidates: pd.DataFrame,
    epoch_rows: pd.DataFrame,
    config: PeriodPriorConfig = PeriodPriorConfig(),
) -> pd.DataFrame:
    """Score candidates against independent RV visits without classifying objects."""

    _require_columns(candidates, _REQUIRED_CANDIDATE_COLUMNS, "candidates")
    _require_columns(epoch_rows, _REQUIRED_EPOCH_COLUMNS, "epoch_rows")
    candidate_ids = pd.to_numeric(candidates["source_id"], errors="raise").astype("int64")
    if candidate_ids.duplicated().any():
        raise ValueError("candidates contain duplicate source_id rows")
    epochs = epoch_rows.copy()
    epochs["source_id"] = pd.to_numeric(epochs["source_id"], errors="raise").astype("int64")
    grouped = {int(key): value for key, value in epochs.groupby("source_id", sort=False)}

    records: list[dict[str, Any]] = []
    for candidate in candidates.assign(source_id=candidate_ids).itertuples(index=False):
        source_id = int(candidate.source_id)
        source_epochs = grouped.get(source_id, epochs.iloc[0:0])
        visits, clean_exposure_count = _prepare_analysis_visits(source_epochs, config)
        record: dict[str, Any] = {
            "source_id": source_id,
            "status": "insufficient_independent_visits",
            "error": "",
            "n_raw_epochs": int(len(source_epochs)),
            "n_clean_exposures": clean_exposure_count,
            "n_independent_visits": int(len(visits)),
            "fit_period_days": getattr(candidate, "fit_period"),
            "fit_period_errup_days": getattr(candidate, "fit_period_errup"),
            "fit_period_errlow_days": getattr(candidate, "fit_period_errlow"),
        }
        for optional in ("population", "priority_rank", "followup_score"):
            if hasattr(candidate, optional):
                record[optional] = getattr(candidate, optional)
        if len(visits) < config.minimum_independent_visits:
            records.append(record)
            continue
        try:
            periods = period_prior_grid(
                getattr(candidate, "fit_period"),
                getattr(candidate, "fit_period_errup"),
                getattr(candidate, "fit_period_errlow"),
                config,
            )
            mjd = visits["mjd"].to_numpy(dtype=float)
            velocity = visits["vrad"].to_numpy(dtype=float)
            quoted_error = visits["vrad_err"].to_numpy(dtype=float)
            effective_error = np.sqrt(quoted_error**2 + config.jitter_kms**2)
            best = scan_period_prior(mjd, velocity, effective_error, periods)
            false_alarm, null_median, null_maximum = permutation_false_alarm_probability(
                mjd,
                velocity,
                effective_error,
                periods,
                best["delta_bic_constant_minus_periodic"],
                source_id=source_id,
                repetitions=config.permutation_repetitions,
                base_seed=config.base_seed,
            )
            central_period = float(getattr(candidate, "fit_period"))
            baseline = float(np.max(mjd) - np.min(mjd))
            best_period = best["best_period_days"]
            constant_p = float(
                chi2_distribution.sf(best["constant_chi2"], int(best["constant_dof"]))
            )
            record.update(best)
            record.update(
                {
                    "status": "scored",
                    "period_grid_min_days": float(periods[0]),
                    "period_grid_max_days": float(periods[-1]),
                    "period_grid_count": int(len(periods)),
                    "best_to_published_period_ratio": best_period / central_period,
                    "baseline_days": baseline,
                    "baseline_over_best_period": baseline / best_period,
                    "phase_coverage": orbital_phase_coverage(mjd, best_period, float(mjd[0])),
                    "max_pairwise_rv_significance": rv_pairwise_significance(
                        velocity, effective_error
                    ),
                    "constant_velocity_p_value": constant_p,
                    "permutation_false_alarm_probability": false_alarm,
                    "permutation_null_delta_bic_median": null_median,
                    "permutation_null_delta_bic_maximum": null_maximum,
                    "maximum_exposures_per_visit": int(
                        visits["n_exposures"].max()
                        if "n_exposures" in visits and not visits.empty
                        else 1
                    ),
                    "maximum_visit_error_inflation": float(
                        visits["error_inflation_factor"].max()
                        if "error_inflation_factor" in visits and not visits.empty
                        else 1.0
                    ),
                }
            )
        except (KeyError, TypeError, ValueError, RuntimeError, np.linalg.LinAlgError) as error:
            record["status"] = "model_error"
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)

    result = pd.DataFrame.from_records(records)
    if not result.empty:
        result = result.sort_values("source_id", kind="stable").reset_index(drop=True)
    return result


def candidate_safe_period_summary(scores: pd.DataFrame) -> dict[str, Any]:
    """Aggregate scores without leaking identifiers, coordinates, or velocities."""

    status_counts = {
        str(key): int(value)
        for key, value in scores.get("status", pd.Series(dtype=str)).value_counts().items()
    }
    scored = scores.loc[scores.get("status", pd.Series(dtype=str)).eq("scored")].copy()
    payload: dict[str, Any] = {
        "score_rows": int(len(scores)),
        "status_counts": status_counts,
        "scored_rows": int(len(scored)),
        "claim_boundary": (
            "Period-prior circular-RV triage only. No row is classified as a binary, "
            "compact object, neutron star, or black hole."
        ),
    }
    if scored.empty:
        payload.update(
            {
                "delta_bic_threshold_counts": {},
                "false_alarm_threshold_counts": {},
                "visit_count_summary": {},
            }
        )
        return payload
    delta_bic = pd.to_numeric(
        scored["delta_bic_constant_minus_periodic"], errors="coerce"
    )
    false_alarm = pd.to_numeric(
        scored["permutation_false_alarm_probability"], errors="coerce"
    )
    visits = pd.to_numeric(scored["n_independent_visits"], errors="coerce")
    payload.update(
        {
            "delta_bic_threshold_counts": {
                "ge_6": int(delta_bic.ge(6.0).sum()),
                "ge_10": int(delta_bic.ge(10.0).sum()),
                "ge_20": int(delta_bic.ge(20.0).sum()),
            },
            "false_alarm_threshold_counts": {
                "le_0.10": int(false_alarm.le(0.10).sum()),
                "le_0.05": int(false_alarm.le(0.05).sum()),
                "le_0.01": int(false_alarm.le(0.01).sum()),
            },
            "joint_followup_counts": {
                "delta_bic_ge_10_and_fap_le_0.05": int(
                    (delta_bic.ge(10.0) & false_alarm.le(0.05)).sum()
                ),
                "delta_bic_ge_20_and_fap_le_0.01": int(
                    (delta_bic.ge(20.0) & false_alarm.le(0.01)).sum()
                ),
            },
            "visit_count_summary": {
                "minimum": int(visits.min()),
                "median": float(visits.median()),
                "maximum": int(visits.max()),
            },
        }
    )
    return payload
