"""Dynamical mass-function and geometry audits for Dark-668 RV targets.

This module is downstream of exact survey identity, clean independent visits,
period-prior triage, and a successful full Keplerian fit. It converts the fitted
period, semi-amplitude, and eccentricity into the single-lined spectroscopic mass
function and an edge-on minimum companion mass. These are physical consistency
checks and follow-up gates, not compact-object classifications.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import brentq

_G_SI = 6.67430e-11
_M_SUN_KG = 1.98847e30
_R_SUN_M = 6.957e8
_DAY_SECONDS = 86_400.0

_REQUIRED_CANDIDATE_COLUMNS = {
    "source_id",
    "mass",
    "radius",
    "fit_companion_mass",
    "fit_companion_mass_errup",
    "fit_companion_mass_errlow",
}
_REQUIRED_KEPLER_COLUMNS = {
    "source_id",
    "status",
    "period_days",
    "semi_amplitude_kms",
    "eccentricity",
    "delta_bic_circular_minus_keplerian",
    "reduced_chi2",
}


@dataclass(frozen=True)
class DynamicalAuditConfig:
    """Frozen descriptive gates for the first physical RV audit."""

    minimum_kepler_delta_bic: float = 6.0
    maximum_reduced_chi2: float = 5.0
    minimum_companion_mass_solar: float = 3.0
    maximum_roche_fill_proxy: float = 0.8

    def __post_init__(self) -> None:
        for name, value in (
            ("minimum_kepler_delta_bic", self.minimum_kepler_delta_bic),
            ("maximum_reduced_chi2", self.maximum_reduced_chi2),
            ("minimum_companion_mass_solar", self.minimum_companion_mass_solar),
            ("maximum_roche_fill_proxy", self.maximum_roche_fill_proxy),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.maximum_reduced_chi2 <= 0:
            raise ValueError("maximum_reduced_chi2 must be positive")
        if self.minimum_companion_mass_solar < 0:
            raise ValueError("minimum_companion_mass_solar must be non-negative")
        if self.maximum_roche_fill_proxy <= 0:
            raise ValueError("maximum_roche_fill_proxy must be positive")

    def to_record(self) -> dict[str, float]:
        return asdict(self)


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing columns: {missing}")


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_positive(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _finite_nonnegative(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and number >= 0 else None


def spectroscopic_mass_function_solar(
    period_days: float,
    semi_amplitude_kms: float,
    eccentricity: float,
) -> float:
    """Return the single-lined spectroscopic mass function in solar masses.

    ``f(M) = P K^3 (1-e^2)^(3/2) / (2 pi G)``.
    """

    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError("period_days must be finite and positive")
    if not math.isfinite(semi_amplitude_kms) or semi_amplitude_kms < 0:
        raise ValueError("semi_amplitude_kms must be finite and non-negative")
    if not math.isfinite(eccentricity) or not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must lie in [0, 1)")
    period_seconds = period_days * _DAY_SECONDS
    amplitude_ms = semi_amplitude_kms * 1_000.0
    value_kg = (
        period_seconds
        * amplitude_ms**3
        * (1.0 - eccentricity**2) ** 1.5
        / (2.0 * math.pi * _G_SI)
    )
    return float(value_kg / _M_SUN_KG)


def minimum_companion_mass_solar(
    mass_function_solar: float,
    primary_mass_solar: float,
) -> float:
    """Solve the edge-on minimum companion mass from an SB1 mass function."""

    if not math.isfinite(mass_function_solar) or mass_function_solar < 0:
        raise ValueError("mass_function_solar must be finite and non-negative")
    if not math.isfinite(primary_mass_solar) or primary_mass_solar <= 0:
        raise ValueError("primary_mass_solar must be finite and positive")
    if mass_function_solar == 0:
        return 0.0

    def equation(companion_mass: float) -> float:
        return (
            companion_mass**3 / (primary_mass_solar + companion_mass) ** 2
            - mass_function_solar
        )

    upper = max(1.0, primary_mass_solar, mass_function_solar)
    while equation(upper) < 0:
        upper *= 2.0
        if upper > 1e7:
            raise RuntimeError("failed to bracket minimum companion mass")
    return float(brentq(equation, 0.0, upper, xtol=1e-12, rtol=1e-12))


def relative_semimajor_axis_rsun(
    period_days: float,
    primary_mass_solar: float,
    companion_mass_solar: float,
) -> float:
    """Return the relative-orbit semimajor axis in solar radii."""

    if not math.isfinite(period_days) or period_days <= 0:
        raise ValueError("period_days must be finite and positive")
    if not math.isfinite(primary_mass_solar) or primary_mass_solar <= 0:
        raise ValueError("primary_mass_solar must be finite and positive")
    if not math.isfinite(companion_mass_solar) or companion_mass_solar < 0:
        raise ValueError("companion_mass_solar must be finite and non-negative")
    total_mass_kg = (primary_mass_solar + companion_mass_solar) * _M_SUN_KG
    period_seconds = period_days * _DAY_SECONDS
    axis_m = (
        _G_SI * total_mass_kg * period_seconds**2 / (4.0 * math.pi**2)
    ) ** (1.0 / 3.0)
    return float(axis_m / _R_SUN_M)


def eggleton_roche_fraction(mass_ratio_primary_to_companion: float) -> float:
    """Return the Eggleton primary Roche-lobe radius divided by separation."""

    ratio = mass_ratio_primary_to_companion
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("mass ratio must be finite and positive")
    ratio_third = ratio ** (1.0 / 3.0)
    ratio_two_thirds = ratio_third**2
    return float(
        0.49
        * ratio_two_thirds
        / (0.6 * ratio_two_thirds + math.log1p(ratio_third))
    )


def primary_roche_geometry_proxy(
    period_days: float,
    eccentricity: float,
    primary_mass_solar: float,
    minimum_companion_mass: float,
    primary_radius_solar: float,
) -> dict[str, float]:
    """Return an edge-on/minimum-mass periastron Roche-geometry proxy.

    This is not a conservative exclusion for every inclination. It is a deterministic
    first audit that identifies obviously contact-like or physically strained fits.
    """

    if not math.isfinite(eccentricity) or not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must lie in [0, 1)")
    if not math.isfinite(primary_radius_solar) or primary_radius_solar <= 0:
        raise ValueError("primary_radius_solar must be finite and positive")
    if minimum_companion_mass <= 0:
        return {
            "relative_semimajor_axis_rsun": math.nan,
            "periastron_separation_rsun": math.nan,
            "primary_roche_lobe_periastron_rsun_proxy": math.nan,
            "primary_roche_fill_factor_proxy": math.nan,
        }
    axis = relative_semimajor_axis_rsun(
        period_days,
        primary_mass_solar,
        minimum_companion_mass,
    )
    periastron = axis * (1.0 - eccentricity)
    roche_fraction = eggleton_roche_fraction(
        primary_mass_solar / minimum_companion_mass
    )
    roche_radius = periastron * roche_fraction
    return {
        "relative_semimajor_axis_rsun": axis,
        "periastron_separation_rsun": periastron,
        "primary_roche_lobe_periastron_rsun_proxy": roche_radius,
        "primary_roche_fill_factor_proxy": primary_radius_solar / roche_radius,
    }


def _mass_function_bounds(
    period_days: float,
    amplitude_kms: float,
    eccentricity: float,
    period_error_days: object,
    amplitude_error_kms: object,
    eccentricity_error: object,
) -> tuple[float, float]:
    period_error = _finite_nonnegative(period_error_days)
    amplitude_error = _finite_nonnegative(amplitude_error_kms)
    eccentricity_sigma = _finite_nonnegative(eccentricity_error)
    if period_error is None or amplitude_error is None or eccentricity_sigma is None:
        return math.nan, math.nan
    period_low = max(period_days - period_error, np.finfo(float).tiny)
    period_high = period_days + period_error
    amplitude_low = max(amplitude_kms - amplitude_error, 0.0)
    amplitude_high = amplitude_kms + amplitude_error
    eccentricity_low = float(np.clip(eccentricity - eccentricity_sigma, 0.0, 0.999999))
    eccentricity_high = float(np.clip(eccentricity + eccentricity_sigma, 0.0, 0.999999))
    lower = spectroscopic_mass_function_solar(
        period_low,
        amplitude_low,
        eccentricity_high,
    )
    upper = spectroscopic_mass_function_solar(
        period_high,
        amplitude_high,
        eccentricity_low,
    )
    return lower, upper


def _published_interval(row: dict[str, Any]) -> tuple[float, float, float]:
    center = _finite_positive(row.get("fit_companion_mass"))
    error_up = _finite_nonnegative(row.get("fit_companion_mass_errup"))
    error_low = _finite_nonnegative(row.get("fit_companion_mass_errlow"))
    if center is None:
        return math.nan, math.nan, math.nan
    lower = max(0.0, center - error_low) if error_low is not None else math.nan
    upper = center + error_up if error_up is not None else math.nan
    return center, lower, upper


def score_dynamical_consistency(
    candidates: pd.DataFrame,
    kepler_scores: pd.DataFrame,
    config: DynamicalAuditConfig = DynamicalAuditConfig(),
) -> pd.DataFrame:
    """Join Kepler fits to catalogue stellar estimates and audit physical consistency."""

    _require_columns(candidates, _REQUIRED_CANDIDATE_COLUMNS, "candidates")
    _require_columns(kepler_scores, _REQUIRED_KEPLER_COLUMNS, "kepler_scores")
    candidate = candidates.copy()
    kepler = kepler_scores.copy()
    candidate["source_id"] = pd.to_numeric(candidate["source_id"], errors="raise").astype(
        "int64"
    )
    kepler["source_id"] = pd.to_numeric(kepler["source_id"], errors="raise").astype(
        "int64"
    )
    if candidate["source_id"].duplicated().any():
        raise ValueError("candidates contain duplicate source_id rows")
    if kepler["source_id"].duplicated().any():
        raise ValueError("kepler_scores contain duplicate source_id rows")

    candidate_map = {
        int(row["source_id"]): row for row in candidate.to_dict(orient="records")
    }
    records: list[dict[str, Any]] = []
    for fit in kepler.to_dict(orient="records"):
        source_id = int(fit["source_id"])
        record: dict[str, Any] = {
            "source_id": source_id,
            "status": "not_keplerian_scored",
            "error": "",
            "kepler_status": fit.get("status"),
        }
        star = candidate_map.get(source_id)
        if star is None:
            record["status"] = "missing_candidate_row"
            records.append(record)
            continue
        for optional in ("population", "priority_rank", "followup_score"):
            if optional in star:
                record[optional] = star[optional]
        if fit.get("status") != "scored":
            records.append(record)
            continue

        try:
            primary_mass = _finite_positive(star.get("mass"))
            primary_radius = _finite_positive(star.get("radius"))
            period = _finite_positive(fit.get("period_days"))
            amplitude = _finite_nonnegative(fit.get("semi_amplitude_kms"))
            eccentricity = _finite_nonnegative(fit.get("eccentricity"))
            if primary_mass is None:
                raise ValueError("primary mass is missing or non-positive")
            if primary_radius is None:
                raise ValueError("primary radius is missing or non-positive")
            if period is None or amplitude is None or eccentricity is None:
                raise ValueError("Kepler period, amplitude, or eccentricity is invalid")
            if eccentricity >= 1:
                raise ValueError("Kepler eccentricity must be below one")

            mass_function = spectroscopic_mass_function_solar(
                period,
                amplitude,
                eccentricity,
            )
            minimum_mass = minimum_companion_mass_solar(
                mass_function,
                primary_mass,
            )
            function_low, function_high = _mass_function_bounds(
                period,
                amplitude,
                eccentricity,
                fit.get("period_error_days"),
                fit.get("semi_amplitude_error_kms"),
                fit.get("eccentricity_error"),
            )
            minimum_low = (
                minimum_companion_mass_solar(function_low, primary_mass)
                if math.isfinite(function_low)
                else math.nan
            )
            minimum_high = (
                minimum_companion_mass_solar(function_high, primary_mass)
                if math.isfinite(function_high)
                else math.nan
            )
            published, published_low, published_high = _published_interval(star)
            if math.isfinite(minimum_low) and math.isfinite(published_high):
                consistency = (
                    "rv_minimum_lower_bound_above_published_upper"
                    if minimum_low > published_high
                    else "uncertainty_intervals_not_disjoint"
                )
            elif math.isfinite(published_high) and minimum_mass > published_high:
                consistency = "rv_point_minimum_above_published_upper"
            elif math.isfinite(published_low) and minimum_mass < published_low:
                consistency = "rv_minimum_below_published_interval_expected_for_unknown_inclination"
            else:
                consistency = "point_estimate_or_open_interval"

            geometry = primary_roche_geometry_proxy(
                period,
                eccentricity,
                primary_mass,
                minimum_mass,
                primary_radius,
            )
            delta_bic = _finite(fit.get("delta_bic_circular_minus_keplerian"))
            reduced_chi2 = _finite(fit.get("reduced_chi2"))
            point_mass_gate = minimum_mass >= config.minimum_companion_mass_solar
            lower_mass_gate = (
                math.isfinite(minimum_low)
                and minimum_low >= config.minimum_companion_mass_solar
            )
            roche_fill = geometry["primary_roche_fill_factor_proxy"]
            geometry_gate = (
                math.isfinite(roche_fill)
                and roche_fill <= config.maximum_roche_fill_proxy
            )
            model_gate = (
                delta_bic is not None
                and delta_bic >= config.minimum_kepler_delta_bic
                and reduced_chi2 is not None
                and reduced_chi2 <= config.maximum_reduced_chi2
            )
            record.update(
                {
                    "status": "scored",
                    "primary_mass_solar": primary_mass,
                    "primary_radius_solar": primary_radius,
                    "mass_function_solar": mass_function,
                    "mass_function_lower_solar": function_low,
                    "mass_function_upper_solar": function_high,
                    "minimum_companion_mass_solar": minimum_mass,
                    "minimum_companion_mass_lower_solar": minimum_low,
                    "minimum_companion_mass_upper_solar": minimum_high,
                    "published_companion_mass_solar": published,
                    "published_companion_mass_lower_solar": published_low,
                    "published_companion_mass_upper_solar": published_high,
                    "rv_minimum_to_published_mass_ratio": (
                        minimum_mass / published
                        if math.isfinite(published) and published > 0
                        else math.nan
                    ),
                    "mass_consistency_status": consistency,
                    **geometry,
                    "model_quality_gate": model_gate,
                    "point_mass_gate": point_mass_gate,
                    "lower_bound_mass_gate": lower_mass_gate,
                    "geometry_proxy_gate": geometry_gate,
                    "point_followup_gate": model_gate and point_mass_gate and geometry_gate,
                    "strong_followup_gate": model_gate and lower_mass_gate and geometry_gate,
                    "uncertainty_bracket_available": math.isfinite(minimum_low)
                    and math.isfinite(minimum_high),
                }
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            record["status"] = "physical_audit_error"
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)

    result = pd.DataFrame.from_records(records)
    if not result.empty:
        result = result.sort_values("source_id", kind="stable").reset_index(drop=True)
    return result


def candidate_safe_dynamical_summary(scores: pd.DataFrame) -> dict[str, Any]:
    """Aggregate physical-audit results without identifiers or fitted parameters."""

    status = scores.get("status", pd.Series(dtype=str))
    scored = scores.loc[status.eq("scored")].copy()
    payload: dict[str, Any] = {
        "score_rows": int(len(scores)),
        "status_counts": {
            str(key): int(value) for key, value in status.value_counts().items()
        },
        "scored_rows": int(len(scored)),
        "claim_boundary": (
            "SB1 mass-function, edge-on minimum-mass, and Roche-geometry proxy audit only. "
            "No row is classified as a compact object, neutron star, or black hole."
        ),
    }
    if scored.empty:
        payload.update(
            {
                "minimum_mass_threshold_counts": {},
                "mass_function_threshold_counts": {},
                "mass_consistency_counts": {},
                "geometry_proxy_counts": {},
                "followup_gate_counts": {},
            }
        )
        return payload

    minimum_mass = pd.to_numeric(
        scored["minimum_companion_mass_solar"], errors="coerce"
    )
    minimum_low = pd.to_numeric(
        scored["minimum_companion_mass_lower_solar"], errors="coerce"
    )
    mass_function = pd.to_numeric(scored["mass_function_solar"], errors="coerce")
    roche_fill = pd.to_numeric(
        scored["primary_roche_fill_factor_proxy"], errors="coerce"
    )
    payload.update(
        {
            "minimum_mass_threshold_counts": {
                "point_ge_3": int(minimum_mass.ge(3.0).sum()),
                "point_ge_5": int(minimum_mass.ge(5.0).sum()),
                "point_ge_10": int(minimum_mass.ge(10.0).sum()),
                "lower_ge_3": int(minimum_low.ge(3.0).sum()),
                "lower_ge_5": int(minimum_low.ge(5.0).sum()),
            },
            "mass_function_threshold_counts": {
                "ge_1": int(mass_function.ge(1.0).sum()),
                "ge_3": int(mass_function.ge(3.0).sum()),
                "ge_5": int(mass_function.ge(5.0).sum()),
            },
            "mass_consistency_counts": {
                str(key): int(value)
                for key, value in scored["mass_consistency_status"]
                .value_counts()
                .items()
            },
            "geometry_proxy_counts": {
                "roche_fill_le_0.5": int(roche_fill.le(0.5).sum()),
                "roche_fill_le_0.8": int(roche_fill.le(0.8).sum()),
                "roche_fill_ge_1": int(roche_fill.ge(1.0).sum()),
            },
            "followup_gate_counts": {
                "point_followup": int(scored["point_followup_gate"].astype(bool).sum()),
                "strong_followup": int(scored["strong_followup_gate"].astype(bool).sum()),
                "uncertainty_bracket_available": int(
                    scored["uncertainty_bracket_available"].astype(bool).sum()
                ),
            },
        }
    )
    return payload
