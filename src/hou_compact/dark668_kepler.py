"""Full Keplerian follow-up fitting for period-prior Dark-668 RV targets.

This module is a second-stage model check.  It is intentionally downstream of
exact survey identity, per-spectrum uncertainty recovery, quality filtering, and
period-prior circular-RV triage.  A successful fit is not a compact-object
classification: stellar, blend, hierarchy, activity, and novelty audits remain
mandatory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from hou_compact.dark668_rv import (
    PeriodPriorConfig,
    deterministic_source_seed,
    period_prior_grid,
    scan_period_prior,
)
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
class KeplerianConfig:
    """Frozen settings for full Keplerian RV follow-up."""

    minimum_independent_visits: int = 7
    minimum_circular_delta_bic: float = 6.0
    period_grid_size: int = 192
    posterior_sigma_span: float = 3.0
    fallback_period_factor: float = 2.0
    minimum_period_days: float = 0.25
    maximum_period_days: float = 50_000.0
    maximum_eccentricity: float = 0.95
    random_starts: int = 32
    maximum_function_evaluations: int = 4_000
    minimum_arm_sn: float = 2.0
    maximum_vrad_error_kms: float = 20.0
    jitter_kms: float = 0.0
    maximum_visit_gap_hours: float = 2.0
    visit_error_floor_kms: float = 0.0
    base_seed: int = 20260723

    def __post_init__(self) -> None:
        if self.minimum_independent_visits < 7:
            raise ValueError("minimum_independent_visits must be at least 7")
        if not math.isfinite(self.minimum_circular_delta_bic):
            raise ValueError("minimum_circular_delta_bic must be finite")
        if self.period_grid_size < 16:
            raise ValueError("period_grid_size must be at least 16")
        for name, value in (
            ("posterior_sigma_span", self.posterior_sigma_span),
            ("fallback_period_factor", self.fallback_period_factor),
            ("minimum_period_days", self.minimum_period_days),
            ("maximum_period_days", self.maximum_period_days),
            ("minimum_arm_sn", self.minimum_arm_sn),
            ("maximum_vrad_error_kms", self.maximum_vrad_error_kms),
            ("maximum_visit_gap_hours", self.maximum_visit_gap_hours),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.fallback_period_factor <= 1:
            raise ValueError("fallback_period_factor must exceed one")
        if self.maximum_period_days <= self.minimum_period_days:
            raise ValueError("maximum_period_days must exceed minimum_period_days")
        if not 0 < self.maximum_eccentricity < 1:
            raise ValueError("maximum_eccentricity must lie strictly between zero and one")
        if self.random_starts < 0:
            raise ValueError("random_starts must be non-negative")
        if self.maximum_function_evaluations < 100:
            raise ValueError("maximum_function_evaluations must be at least 100")
        if not math.isfinite(self.jitter_kms) or self.jitter_kms < 0:
            raise ValueError("jitter_kms must be finite and non-negative")
        if (
            not math.isfinite(self.visit_error_floor_kms)
            or self.visit_error_floor_kms < 0
        ):
            raise ValueError("visit_error_floor_kms must be finite and non-negative")

    def period_config(self) -> PeriodPriorConfig:
        return PeriodPriorConfig(
            minimum_independent_visits=max(4, self.minimum_independent_visits),
            period_grid_size=self.period_grid_size,
            posterior_sigma_span=self.posterior_sigma_span,
            fallback_period_factor=self.fallback_period_factor,
            minimum_period_days=self.minimum_period_days,
            maximum_period_days=self.maximum_period_days,
            minimum_arm_sn=self.minimum_arm_sn,
            maximum_vrad_error_kms=self.maximum_vrad_error_kms,
            jitter_kms=self.jitter_kms,
            aggregate_visits=True,
            maximum_visit_gap_hours=self.maximum_visit_gap_hours,
            visit_error_floor_kms=self.visit_error_floor_kms,
            permutation_repetitions=0,
            base_seed=self.base_seed,
        )

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing columns: {missing}")


def solve_kepler_equation(
    mean_anomaly: np.ndarray,
    eccentricity: float,
    *,
    tolerance: float = 1e-12,
    maximum_iterations: int = 80,
) -> np.ndarray:
    """Solve ``E - e sin(E) = M`` by safeguarded vectorized Newton iteration."""

    mean = np.asarray(mean_anomaly, dtype=float)
    if not np.all(np.isfinite(mean)):
        raise ValueError("mean_anomaly must be finite")
    if not math.isfinite(eccentricity) or not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must lie in [0, 1)")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    if maximum_iterations < 1:
        raise ValueError("maximum_iterations must be positive")

    wrapped = np.remainder(mean + np.pi, 2.0 * np.pi) - np.pi
    if eccentricity < 0.8:
        eccentric = wrapped.copy()
    else:
        eccentric = np.where(wrapped >= 0.0, np.pi, -np.pi)
    converged = np.zeros(mean.shape, dtype=bool)
    for _ in range(maximum_iterations):
        residual = eccentric - eccentricity * np.sin(eccentric) - wrapped
        derivative = 1.0 - eccentricity * np.cos(eccentric)
        step = residual / derivative
        eccentric -= step
        converged |= np.abs(step) <= tolerance
        if bool(np.all(converged)):
            return eccentric
    maximum_residual = float(
        np.max(np.abs(eccentric - eccentricity * np.sin(eccentric) - wrapped))
    )
    raise RuntimeError(
        "Kepler equation did not converge; "
        f"maximum residual={maximum_residual:.3e}"
    )


def keplerian_velocity(
    mjd: np.ndarray,
    *,
    period_days: float,
    semi_amplitude_kms: float,
    eccentricity: float,
    omega_radians: float,
    mean_anomaly_reference_radians: float,
    systemic_velocity_kms: float,
    reference_mjd: float | None = None,
) -> np.ndarray:
    """Evaluate a single-lined Keplerian radial-velocity curve."""

    time = np.asarray(mjd, dtype=float)
    if not np.all(np.isfinite(time)):
        raise ValueError("mjd must be finite")
    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError("period_days must be finite and positive")
    if not math.isfinite(semi_amplitude_kms) or semi_amplitude_kms < 0:
        raise ValueError("semi_amplitude_kms must be finite and non-negative")
    if not math.isfinite(eccentricity) or not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must lie in [0, 1)")
    for name, value in (
        ("omega_radians", omega_radians),
        ("mean_anomaly_reference_radians", mean_anomaly_reference_radians),
        ("systemic_velocity_kms", systemic_velocity_kms),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    origin = float(np.min(time)) if reference_mjd is None else float(reference_mjd)
    if not math.isfinite(origin):
        raise ValueError("reference_mjd must be finite")
    mean_anomaly = (
        mean_anomaly_reference_radians
        + 2.0 * np.pi * (time - origin) / period_days
    )
    eccentric_anomaly = solve_kepler_equation(mean_anomaly, eccentricity)
    numerator = np.sqrt(1.0 - eccentricity**2) * np.sin(eccentric_anomaly)
    denominator = np.cos(eccentric_anomaly) - eccentricity
    true_anomaly = np.arctan2(numerator, denominator)
    return systemic_velocity_kms + semi_amplitude_kms * (
        np.cos(true_anomaly + omega_radians)
        + eccentricity * np.cos(omega_radians)
    )


def _bic(chi2: float, free_parameters: int, observations: int) -> float:
    if observations <= free_parameters:
        return math.inf
    return float(chi2 + free_parameters * math.log(observations))


def _parameter_bounds(
    velocity: np.ndarray,
    period_lower: float,
    period_upper: float,
    maximum_eccentricity: float,
) -> tuple[np.ndarray, np.ndarray]:
    minimum_velocity = float(np.min(velocity))
    maximum_velocity = float(np.max(velocity))
    span = max(maximum_velocity - minimum_velocity, 1.0)
    gamma_padding = max(10.0 * span, 100.0)
    maximum_amplitude = max(20.0 * span, 1_000.0)
    lower = np.asarray(
        [
            minimum_velocity - gamma_padding,
            math.log(1e-3),
            0.0,
            -np.pi,
            -np.pi,
            math.log(period_lower),
        ],
        dtype=float,
    )
    upper = np.asarray(
        [
            maximum_velocity + gamma_padding,
            math.log(maximum_amplitude),
            maximum_eccentricity,
            np.pi,
            np.pi,
            math.log(period_upper),
        ],
        dtype=float,
    )
    return lower, upper


def _decode_parameters(parameters: np.ndarray) -> dict[str, float]:
    gamma, log_amplitude, eccentricity, omega, mean_anomaly, log_period = parameters
    return {
        "systemic_velocity_kms": float(gamma),
        "semi_amplitude_kms": float(math.exp(log_amplitude)),
        "eccentricity": float(eccentricity),
        "omega_radians": float(omega),
        "mean_anomaly_reference_radians": float(mean_anomaly),
        "period_days": float(math.exp(log_period)),
    }


def _fit_covariance(
    jacobian: np.ndarray,
    chi2: float,
    dof: int,
) -> np.ndarray | None:
    if dof <= 0 or jacobian.ndim != 2:
        return None
    normal = jacobian.T @ jacobian
    if np.linalg.matrix_rank(normal) < normal.shape[0]:
        return None
    try:
        covariance = np.linalg.inv(normal) * (chi2 / dof)
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(covariance)):
        return None
    return covariance


def _initial_vectors(
    velocity: np.ndarray,
    period_lower: float,
    period_upper: float,
    central_period: float,
    circular_period: float,
    source_id: int,
    config: KeplerianConfig,
) -> list[np.ndarray]:
    median = float(np.median(velocity))
    robust_amplitude = max(
        0.5 * float(np.quantile(velocity, 0.9) - np.quantile(velocity, 0.1)),
        0.1,
    )
    periods = [
        float(np.clip(central_period, period_lower, period_upper)),
        float(np.clip(circular_period, period_lower, period_upper)),
        float(math.sqrt(period_lower * period_upper)),
    ]
    starts: list[np.ndarray] = []
    for period, eccentricity, omega, mean_anomaly in (
        (periods[0], 0.05, 0.0, 0.0),
        (periods[1], 0.25, np.pi / 2.0, -np.pi / 2.0),
        (periods[2], 0.60, -np.pi / 2.0, np.pi / 2.0),
    ):
        starts.append(
            np.asarray(
                [
                    median,
                    math.log(robust_amplitude),
                    min(eccentricity, config.maximum_eccentricity * 0.95),
                    omega,
                    mean_anomaly,
                    math.log(period),
                ],
                dtype=float,
            )
        )
    generator = np.random.default_rng(
        deterministic_source_seed(source_id, config.base_seed, "keplerian_multistart")
    )
    for _ in range(config.random_starts):
        starts.append(
            np.asarray(
                [
                    median + generator.normal(0.0, robust_amplitude),
                    math.log(robust_amplitude)
                    + generator.normal(0.0, 0.7),
                    config.maximum_eccentricity * generator.beta(1.2, 2.5),
                    generator.uniform(-np.pi, np.pi),
                    generator.uniform(-np.pi, np.pi),
                    generator.uniform(math.log(period_lower), math.log(period_upper)),
                ],
                dtype=float,
            )
        )
    return starts


def fit_keplerian_period_prior(
    mjd: np.ndarray,
    velocity: np.ndarray,
    error: np.ndarray,
    *,
    central_period_days: float,
    period_error_up_days: float,
    period_error_low_days: float,
    source_id: int,
    config: KeplerianConfig = KeplerianConfig(),
) -> dict[str, Any]:
    """Fit a bounded six-parameter Keplerian model with deterministic multistart."""

    time = np.asarray(mjd, dtype=float)
    rv = np.asarray(velocity, dtype=float)
    uncertainty = np.asarray(error, dtype=float)
    if time.ndim != 1 or rv.ndim != 1 or uncertainty.ndim != 1:
        raise ValueError("mjd, velocity, and error must be one-dimensional")
    if not (len(time) == len(rv) == len(uncertainty)):
        raise ValueError("mjd, velocity, and error lengths disagree")
    if len(time) < config.minimum_independent_visits:
        raise ValueError("insufficient independent visits for Keplerian fit")
    if not np.all(np.isfinite(time)) or not np.all(np.isfinite(rv)):
        raise ValueError("mjd and velocity must be finite")
    if not np.all(np.isfinite(uncertainty)) or np.any(uncertainty <= 0):
        raise ValueError("error must contain finite positive values")

    periods = period_prior_grid(
        central_period_days,
        period_error_up_days,
        period_error_low_days,
        config.period_config(),
    )
    period_lower = float(periods[0])
    period_upper = float(periods[-1])
    circular = scan_period_prior(time, rv, uncertainty, periods)
    reference_mjd = float(np.min(time))
    lower, upper = _parameter_bounds(
        rv,
        period_lower,
        period_upper,
        config.maximum_eccentricity,
    )

    def residual(parameters: np.ndarray) -> np.ndarray:
        decoded = _decode_parameters(parameters)
        model = keplerian_velocity(
            time,
            period_days=decoded["period_days"],
            semi_amplitude_kms=decoded["semi_amplitude_kms"],
            eccentricity=decoded["eccentricity"],
            omega_radians=decoded["omega_radians"],
            mean_anomaly_reference_radians=decoded[
                "mean_anomaly_reference_radians"
            ],
            systemic_velocity_kms=decoded["systemic_velocity_kms"],
            reference_mjd=reference_mjd,
        )
        return (rv - model) / uncertainty

    best_result = None
    attempted = 0
    successful = 0
    for initial in _initial_vectors(
        rv,
        period_lower,
        period_upper,
        float(central_period_days),
        float(circular["best_period_days"]),
        int(source_id),
        config,
    ):
        attempted += 1
        clipped = np.clip(initial, lower + 1e-10, upper - 1e-10)
        try:
            result = least_squares(
                residual,
                clipped,
                bounds=(lower, upper),
                method="trf",
                loss="linear",
                max_nfev=config.maximum_function_evaluations,
                xtol=1e-11,
                ftol=1e-11,
                gtol=1e-11,
            )
        except (FloatingPointError, RuntimeError, ValueError):
            continue
        if not result.success or not np.all(np.isfinite(result.x)):
            continue
        successful += 1
        chi2 = float(result.fun @ result.fun)
        if best_result is None or chi2 < float(best_result.fun @ best_result.fun):
            best_result = result
    if best_result is None:
        raise RuntimeError("all Keplerian optimization starts failed")

    decoded = _decode_parameters(best_result.x)
    chi2 = float(best_result.fun @ best_result.fun)
    dof = len(time) - 6
    bic = _bic(chi2, 6, len(time))
    covariance = _fit_covariance(best_result.jac, chi2, dof)
    uncertainties = {
        "systemic_velocity_error_kms": math.nan,
        "semi_amplitude_error_kms": math.nan,
        "eccentricity_error": math.nan,
        "omega_error_radians": math.nan,
        "mean_anomaly_reference_error_radians": math.nan,
        "period_error_days": math.nan,
    }
    if covariance is not None:
        standard = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        uncertainties = {
            "systemic_velocity_error_kms": float(standard[0]),
            "semi_amplitude_error_kms": float(
                decoded["semi_amplitude_kms"] * standard[1]
            ),
            "eccentricity_error": float(standard[2]),
            "omega_error_radians": float(standard[3]),
            "mean_anomaly_reference_error_radians": float(standard[4]),
            "period_error_days": float(decoded["period_days"] * standard[5]),
        }
    model = keplerian_velocity(
        time,
        period_days=decoded["period_days"],
        semi_amplitude_kms=decoded["semi_amplitude_kms"],
        eccentricity=decoded["eccentricity"],
        omega_radians=decoded["omega_radians"],
        mean_anomaly_reference_radians=decoded[
            "mean_anomaly_reference_radians"
        ],
        systemic_velocity_kms=decoded["systemic_velocity_kms"],
        reference_mjd=reference_mjd,
    )
    output: dict[str, Any] = {
        **decoded,
        **uncertainties,
        "reference_mjd": reference_mjd,
        "chi2": chi2,
        "dof": dof,
        "reduced_chi2": chi2 / dof if dof > 0 else math.nan,
        "bic": bic,
        "circular_bic": float(circular["periodic_bic"]),
        "constant_bic": float(circular["constant_bic"]),
        "delta_bic_circular_minus_keplerian": float(
            circular["periodic_bic"] - bic
        ),
        "delta_bic_constant_minus_keplerian": float(
            circular["constant_bic"] - bic
        ),
        "circular_best_period_days": float(circular["best_period_days"]),
        "circular_delta_bic_constant_minus_periodic": float(
            circular["delta_bic_constant_minus_periodic"]
        ),
        "period_prior_lower_days": period_lower,
        "period_prior_upper_days": period_upper,
        "period_to_published_ratio": float(
            decoded["period_days"] / float(central_period_days)
        ),
        "phase_coverage": orbital_phase_coverage(
            time, decoded["period_days"], reference_mjd
        ),
        "baseline_days": float(np.max(time) - np.min(time)),
        "max_pairwise_rv_significance": rv_pairwise_significance(rv, uncertainty),
        "weighted_rms_residual_kms": float(
            np.sqrt(np.average((rv - model) ** 2, weights=1.0 / uncertainty**2))
        ),
        "optimization_starts_attempted": attempted,
        "optimization_starts_successful": successful,
        "optimizer_nfev": int(best_result.nfev),
        "optimizer_optimality": float(best_result.optimality),
        "covariance_available": covariance is not None,
    }
    return output


def _prepare_visits(
    source_epochs: pd.DataFrame,
    config: KeplerianConfig,
) -> tuple[pd.DataFrame, int]:
    clean = source_epochs.loc[
        clean_epoch_mask(
            source_epochs,
            min_arm_sn=config.minimum_arm_sn,
            max_vrad_err=config.maximum_vrad_error_kms,
        )
    ].sort_values("mjd", kind="stable")
    if clean.empty:
        return pd.DataFrame(columns=["source_id", "mjd", "vrad", "vrad_err"]), 0
    visits = aggregate_independent_visits(
        clean,
        maximum_gap_hours=config.maximum_visit_gap_hours,
        error_floor_kms=config.visit_error_floor_kms,
    )
    return visits, int(len(clean))


def score_keplerian_candidates(
    candidates: pd.DataFrame,
    epoch_rows: pd.DataFrame,
    circular_scores: pd.DataFrame | None = None,
    config: KeplerianConfig = KeplerianConfig(),
) -> pd.DataFrame:
    """Fit full Keplerian models only to preselected, sufficiently sampled targets."""

    _require_columns(candidates, _REQUIRED_CANDIDATE_COLUMNS, "candidates")
    _require_columns(epoch_rows, _REQUIRED_EPOCH_COLUMNS, "epoch_rows")
    candidate_ids = pd.to_numeric(candidates["source_id"], errors="raise").astype("int64")
    if candidate_ids.duplicated().any():
        raise ValueError("candidates contain duplicate source_id rows")
    epochs = epoch_rows.copy()
    epochs["source_id"] = pd.to_numeric(epochs["source_id"], errors="raise").astype("int64")
    grouped = {int(key): value for key, value in epochs.groupby("source_id", sort=False)}

    circular_map: dict[int, dict[str, Any]] = {}
    if circular_scores is not None:
        required = {"source_id", "status", "delta_bic_constant_minus_periodic"}
        _require_columns(circular_scores, required, "circular_scores")
        circular = circular_scores.copy()
        circular["source_id"] = pd.to_numeric(
            circular["source_id"], errors="raise"
        ).astype("int64")
        if circular["source_id"].duplicated().any():
            raise ValueError("circular_scores contain duplicate source_id rows")
        circular_map = {
            int(row["source_id"]): row
            for row in circular.to_dict(orient="records")
        }

    records: list[dict[str, Any]] = []
    prepared = candidates.assign(source_id=candidate_ids)
    for candidate in prepared.itertuples(index=False):
        source_id = int(candidate.source_id)
        source_epochs = grouped.get(source_id, epochs.iloc[0:0])
        visits, clean_exposure_count = _prepare_visits(source_epochs, config)
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

        if circular_scores is not None:
            circular_row = circular_map.get(source_id)
            if circular_row is None:
                record["status"] = "missing_circular_score"
                records.append(record)
                continue
            delta = pd.to_numeric(
                pd.Series([circular_row["delta_bic_constant_minus_periodic"]]),
                errors="coerce",
            ).iloc[0]
            record["input_circular_status"] = circular_row["status"]
            record["input_circular_delta_bic"] = delta
            if (
                circular_row["status"] != "scored"
                or not math.isfinite(float(delta))
                or float(delta) < config.minimum_circular_delta_bic
            ):
                record["status"] = "not_preselected"
                records.append(record)
                continue

        if len(visits) < config.minimum_independent_visits:
            records.append(record)
            continue
        try:
            quoted_error = visits["vrad_err"].to_numpy(dtype=float)
            effective_error = np.sqrt(quoted_error**2 + config.jitter_kms**2)
            fit = fit_keplerian_period_prior(
                visits["mjd"].to_numpy(dtype=float),
                visits["vrad"].to_numpy(dtype=float),
                effective_error,
                central_period_days=float(getattr(candidate, "fit_period")),
                period_error_up_days=float(getattr(candidate, "fit_period_errup")),
                period_error_low_days=float(getattr(candidate, "fit_period_errlow")),
                source_id=source_id,
                config=config,
            )
            record.update(fit)
            record["status"] = "scored"
            record["maximum_exposures_per_visit"] = int(
                visits["n_exposures"].max()
                if "n_exposures" in visits.columns
                else 1
            )
            record["maximum_visit_error_inflation"] = float(
                visits["error_inflation_factor"].max()
                if "error_inflation_factor" in visits.columns
                else 1.0
            )
        except (
            FloatingPointError,
            KeyError,
            TypeError,
            ValueError,
            RuntimeError,
            np.linalg.LinAlgError,
        ) as error:
            record["status"] = "model_error"
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)

    result = pd.DataFrame.from_records(records)
    if not result.empty:
        result = result.sort_values("source_id", kind="stable").reset_index(drop=True)
    return result


def candidate_safe_keplerian_summary(scores: pd.DataFrame) -> dict[str, Any]:
    """Aggregate full-orbit fit outcomes without emitting identifiers or parameters."""

    status = scores.get("status", pd.Series(dtype=str))
    scored = scores.loc[status.eq("scored")].copy()
    payload: dict[str, Any] = {
        "score_rows": int(len(scores)),
        "status_counts": {
            str(key): int(value) for key, value in status.value_counts().items()
        },
        "scored_rows": int(len(scored)),
        "claim_boundary": (
            "Full Keplerian RV model comparison only. No row is classified as a binary, "
            "compact object, neutron star, or black hole."
        ),
    }
    if scored.empty:
        payload.update(
            {
                "keplerian_over_circular_threshold_counts": {},
                "eccentricity_bin_counts": {},
                "fit_quality_counts": {},
            }
        )
        return payload
    delta = pd.to_numeric(
        scored["delta_bic_circular_minus_keplerian"], errors="coerce"
    )
    eccentricity = pd.to_numeric(scored["eccentricity"], errors="coerce")
    reduced = pd.to_numeric(scored["reduced_chi2"], errors="coerce")
    covariance = scored.get(
        "covariance_available", pd.Series(False, index=scored.index)
    ).astype(bool)
    payload.update(
        {
            "keplerian_over_circular_threshold_counts": {
                "delta_bic_ge_2": int(delta.ge(2.0).sum()),
                "delta_bic_ge_6": int(delta.ge(6.0).sum()),
                "delta_bic_ge_10": int(delta.ge(10.0).sum()),
            },
            "eccentricity_bin_counts": {
                "lt_0.2": int(eccentricity.lt(0.2).sum()),
                "0.2_to_0.5": int(
                    (eccentricity.ge(0.2) & eccentricity.lt(0.5)).sum()
                ),
                "ge_0.5": int(eccentricity.ge(0.5).sum()),
            },
            "fit_quality_counts": {
                "reduced_chi2_le_2": int(reduced.le(2.0).sum()),
                "reduced_chi2_le_5": int(reduced.le(5.0).sum()),
                "covariance_available": int(covariance.sum()),
            },
        }
    )
    return payload
