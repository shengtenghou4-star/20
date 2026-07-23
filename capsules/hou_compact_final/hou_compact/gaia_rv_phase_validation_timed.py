#!/usr/bin/env python3
"""Strict Gaia/LAMOST phase validation with exact obsid midpoint-time joins."""

from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from gaia_rv_phase_validation import GaiaOrbit, orbit_shape_velocity

_EXACT_OBSID = re.compile(r"^[0-9]+$")
_EXACT_SOURCE = re.compile(r"^[0-9]{10,20}$")
_OBSID_ALIASES = ("obsid", "obs_id")
_SOURCE_ALIASES = ("hou_compact_dr3_source_id", "source_id")
_RV_ALIASES = ("rv", "radial_velocity")
_RV_ERR_ALIASES = ("rv_err", "radial_velocity_error", "radial_velocity_err")
_MID_MJD_ALIASES = ("mid_mjd", "midmjd")
_TIME_ERROR_ALIASES = ("time_quantisation_half_width_days",)


class TimedPhaseError(RuntimeError):
    """Raised when exact obsid, source, RV, or time contracts are violated."""


@dataclass(frozen=True)
class TimedRVPoint:
    obsid: str
    source_id: str
    mjd: float
    time_error_days: float
    rv_kms: float
    rv_error_kms: float


def _normalized_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise TimedPhaseError("table has no header")
    mapping: dict[str, str] = {}
    for original in fieldnames:
        normalized = str(original).strip().lower().lstrip("\ufeff")
        if not normalized or normalized in mapping:
            raise TimedPhaseError("table has empty or duplicate normalized header")
        mapping[normalized] = original
    return mapping


def _resolve(mapping: dict[str, str], aliases: tuple[str, ...], label: str) -> str:
    matches = [mapping[name] for name in aliases if name in mapping]
    if len(matches) != 1:
        raise TimedPhaseError(
            f"expected exactly one {label} column from {aliases!r}; found {matches!r}"
        )
    return matches[0]


def _exact(value: object, pattern: re.Pattern[str], *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not pattern.fullmatch(token):
        raise TimedPhaseError(f"{label} is not an exact integer token")
    return token


def _finite(value: object, *, label: str) -> float:
    token = "" if value is None else str(value)
    if not token or token != token.strip():
        raise TimedPhaseError(f"{label} is missing or contains whitespace")
    try:
        result = float(token)
    except ValueError as error:
        raise TimedPhaseError(f"{label} is not numeric") from error
    if not math.isfinite(result):
        raise TimedPhaseError(f"{label} is not finite")
    return result


def load_exact_timed_rv(
    *,
    rv_path: Path,
    time_path: Path,
) -> dict[str, list[TimedRVPoint]]:
    if not rv_path.exists() or rv_path.stat().st_size == 0:
        raise TimedPhaseError("exact RV table is missing or empty")
    if not time_path.exists() or time_path.stat().st_size == 0:
        raise TimedPhaseError("exact time bridge is missing or empty")

    times: dict[str, tuple[str, float, float]] = {}
    with time_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _normalized_headers(reader.fieldnames)
        obsid_column = _resolve(mapping, _OBSID_ALIASES, "time obsid")
        source_column = _resolve(mapping, _SOURCE_ALIASES, "time source")
        mjd_column = _resolve(mapping, _MID_MJD_ALIASES, "midpoint MJD")
        error_column = _resolve(mapping, _TIME_ERROR_ALIASES, "time quantisation error")
        for row in reader:
            if None in row:
                raise TimedPhaseError("time row has extra fields")
            obsid = _exact(row.get(obsid_column), _EXACT_OBSID, label="time obsid")
            source = _exact(row.get(source_column), _EXACT_SOURCE, label="time source")
            mjd = _finite(row.get(mjd_column), label="midpoint MJD")
            time_error = _finite(
                row.get(error_column), label="time quantisation error"
            )
            if time_error <= 0 or time_error > 0.01:
                raise TimedPhaseError("time quantisation error is outside (0,0.01] day")
            if obsid in times:
                raise TimedPhaseError("time bridge repeats an obsid")
            times[obsid] = (source, mjd, time_error)

    grouped: dict[str, list[TimedRVPoint]] = defaultdict(list)
    rv_obsids: set[str] = set()
    with rv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _normalized_headers(reader.fieldnames)
        obsid_column = _resolve(mapping, _OBSID_ALIASES, "RV obsid")
        source_column = _resolve(mapping, _SOURCE_ALIASES, "RV source")
        rv_column = _resolve(mapping, _RV_ALIASES, "RV")
        rv_err_column = _resolve(mapping, _RV_ERR_ALIASES, "RV error")
        for row in reader:
            if None in row:
                raise TimedPhaseError("RV row has extra fields")
            obsid = _exact(row.get(obsid_column), _EXACT_OBSID, label="RV obsid")
            source = _exact(row.get(source_column), _EXACT_SOURCE, label="RV source")
            if obsid in rv_obsids:
                raise TimedPhaseError("exact RV table repeats an obsid")
            rv_obsids.add(obsid)
            time_record = times.get(obsid)
            if time_record is None:
                continue
            time_source, mjd, time_error = time_record
            if time_source != source:
                raise TimedPhaseError("RV and time bridge disagree on source identity")
            rv = _finite(row.get(rv_column), label="RV")
            rv_error = _finite(row.get(rv_err_column), label="RV error")
            if rv_error <= 0:
                raise TimedPhaseError("RV error must be positive")
            grouped[source].append(
                TimedRVPoint(
                    obsid=obsid,
                    source_id=source,
                    mjd=mjd,
                    time_error_days=time_error,
                    rv_kms=rv,
                    rv_error_kms=rv_error,
                )
            )
    return grouped


def validate_timed_phase(
    orbit: GaiaOrbit,
    points: list[TimedRVPoint],
    *,
    systematic_floor_kms: float = 5.0,
) -> dict[str, object]:
    if not math.isfinite(systematic_floor_kms) or systematic_floor_kms < 0:
        raise ValueError("systematic_floor_kms must be finite and non-negative")
    points = sorted(points, key=lambda point: (point.mjd, point.obsid))
    if len(points) < 2:
        return {
            "rv_epochs_with_exact_time": len(points),
            "phase_test_available": False,
            "strict_phase_supported": False,
        }

    model: list[float] = []
    model_time_errors: list[float] = []
    variances: list[float] = []
    for point in points:
        central = orbit_shape_velocity(orbit, point.mjd)
        lower = orbit_shape_velocity(orbit, point.mjd - point.time_error_days)
        upper = orbit_shape_velocity(orbit, point.mjd + point.time_error_days)
        timing_error = max(abs(central - lower), abs(upper - central))
        variance = (
            point.rv_error_kms**2
            + systematic_floor_kms**2
            + timing_error**2
        )
        model.append(central)
        model_time_errors.append(timing_error)
        variances.append(variance)

    weights = [1.0 / value for value in variances]
    observed = [point.rv_kms for point in points]
    weight_sum = sum(weights)
    constant = sum(weight * value for weight, value in zip(weights, observed)) / weight_sum
    offset = sum(
        weight * (value - prediction)
        for weight, value, prediction in zip(weights, observed, model)
    ) / weight_sum
    chi2_constant = sum(
        (value - constant) ** 2 / variance
        for value, variance in zip(observed, variances)
    )
    chi2_phase = sum(
        (value - prediction - offset) ** 2 / variance
        for value, prediction, variance in zip(observed, model, variances)
    )
    dof = len(points) - 1
    delta_chi2 = chi2_constant - chi2_phase
    predicted_span = max(model) - min(model)
    observed_span = max(observed) - min(observed)

    informative_pairs = 0
    direction_matches = 0
    zero_observed_informative_pairs = 0
    for first in range(len(points)):
        for second in range(first + 1, len(points)):
            predicted_delta = model[second] - model[first]
            observed_delta = observed[second] - observed[first]
            if abs(predicted_delta) < 10.0:
                continue
            informative_pairs += 1
            if observed_delta == 0.0:
                zero_observed_informative_pairs += 1
            elif observed_delta * predicted_delta > 0:
                direction_matches += 1
    direction_fraction = (
        direction_matches / informative_pairs if informative_pairs else None
    )
    reduced_chi2 = chi2_phase / dof
    strict = bool(
        len(points) >= 3
        and predicted_span >= 20.0
        and delta_chi2 >= 9.0
        and reduced_chi2 <= 5.0
        and informative_pairs >= 2
        and direction_fraction is not None
        and direction_fraction >= 0.75
    )
    return {
        "rv_epochs_with_exact_time": len(points),
        "phase_test_available": True,
        "maximum_time_quantisation_half_width_days": max(
            point.time_error_days for point in points
        ),
        "maximum_orbit_velocity_error_from_time_kms": max(model_time_errors),
        "observed_rv_span_kms": observed_span,
        "gaia_predicted_span_kms": predicted_span,
        "fitted_lamost_minus_gaia_offset_kms": offset,
        "chi2_constant": chi2_constant,
        "chi2_gaia_phase": chi2_phase,
        "degrees_of_freedom": dof,
        "delta_chi2_gaia_vs_constant": delta_chi2,
        "gaia_phase_reduced_chi2": reduced_chi2,
        "informative_pairs": informative_pairs,
        "zero_observed_informative_pairs": zero_observed_informative_pairs,
        "pair_direction_match_fraction": direction_fraction,
        "strict_phase_supported": strict,
        "timing_contract": (
            "exact obsid hybrid UTC time; written quantisation propagated to model RV"
        ),
    }
