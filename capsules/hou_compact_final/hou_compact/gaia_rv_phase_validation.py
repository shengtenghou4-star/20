#!/usr/bin/env python3
"""Minimal frozen Gaia SB1/SB1C orbit-shape core for the final encrypted capsule."""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_EXACT_SOURCE_ID = re.compile(r"^[0-9]{10,20}$")
_MISSING = {"", "--", "nan", "NaN", "null", "None"}


class PhaseValidationError(RuntimeError):
    """Raised when a frozen orbit input violates the exact contract."""


@dataclass(frozen=True)
class GaiaOrbit:
    source_id: str
    solution_type: str
    period_days: float
    ref_epoch_jyear: float
    t_periastron_days: float
    eccentricity: float
    arg_periastron_deg: float
    semi_amplitude_kms: float


def _iter_noncomment_lines(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            yield line


def _normalized_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise PhaseValidationError("table has no header")
    mapping: dict[str, str] = {}
    for original in fieldnames:
        normalized = str(original).strip().lower().lstrip("\ufeff")
        if not normalized or normalized in mapping:
            raise PhaseValidationError("table has empty or duplicate normalized header")
        mapping[normalized] = original
    return mapping


def _float_token(value: object, *, label: str, required: bool = True) -> float | None:
    token = "" if value is None else str(value).strip()
    if token in _MISSING:
        if required:
            raise PhaseValidationError(f"missing required {label}")
        return None
    try:
        result = float(token)
    except ValueError as error:
        raise PhaseValidationError(f"{label} is not numeric") from error
    if not math.isfinite(result):
        raise PhaseValidationError(f"{label} is not finite")
    return result


def _source_token(value: object, *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not _EXACT_SOURCE_ID.fullmatch(token):
        raise PhaseValidationError(f"{label} is not an exact source identifier")
    return token


def julian_year_to_mjd(julian_year: float) -> float:
    if not math.isfinite(julian_year):
        raise ValueError("julian_year must be finite")
    return 51544.5 + (julian_year - 2000.0) * 365.25


def _solve_eccentric_anomaly(mean_anomaly: float, eccentricity: float) -> float:
    if not 0 <= eccentricity < 1:
        raise ValueError("eccentricity must be in [0, 1)")
    mean_anomaly = math.fmod(mean_anomaly, 2.0 * math.pi)
    if mean_anomaly < 0:
        mean_anomaly += 2.0 * math.pi
    estimate = mean_anomaly if eccentricity < 0.8 else math.pi
    for _ in range(100):
        numerator = estimate - eccentricity * math.sin(estimate) - mean_anomaly
        denominator = 1.0 - eccentricity * math.cos(estimate)
        update = numerator / denominator
        estimate -= update
        if abs(update) < 1e-13:
            return estimate
    raise PhaseValidationError("Kepler solver did not converge")


def orbit_shape_velocity(orbit: GaiaOrbit, mjd: float) -> float:
    """Return the frozen Gaia RV shape including K1 but excluding systemic velocity."""

    if not math.isfinite(mjd):
        raise ValueError("mjd must be finite")
    periastron_mjd = (
        julian_year_to_mjd(orbit.ref_epoch_jyear) + orbit.t_periastron_days
    )
    phase_angle = 2.0 * math.pi * (mjd - periastron_mjd) / orbit.period_days
    if orbit.solution_type == "SB1C":
        return orbit.semi_amplitude_kms * math.cos(phase_angle)
    eccentric_anomaly = _solve_eccentric_anomaly(phase_angle, orbit.eccentricity)
    numerator = math.sqrt(1.0 + orbit.eccentricity) * math.sin(
        eccentric_anomaly / 2.0
    )
    denominator = math.sqrt(1.0 - orbit.eccentricity) * math.cos(
        eccentric_anomaly / 2.0
    )
    true_anomaly = 2.0 * math.atan2(numerator, denominator)
    omega = math.radians(orbit.arg_periastron_deg)
    return orbit.semi_amplitude_kms * (
        math.cos(true_anomaly + omega) + orbit.eccentricity * math.cos(omega)
    )


def load_gaia_orbits(path: Path) -> dict[str, GaiaOrbit]:
    lines = list(_iter_noncomment_lines(path))
    if not lines:
        raise PhaseValidationError("Gaia orbit table contains no data")
    reader = csv.DictReader(lines, strict=True)
    mapping = _normalized_headers(reader.fieldnames)
    required = (
        "source_id",
        "nss_solution_type",
        "period",
        "gaia_ref_epoch",
        "t_periastron",
        "semi_amplitude_primary",
    )
    missing = [name for name in required if name not in mapping]
    if missing:
        raise PhaseValidationError(f"Gaia orbit table is missing columns: {missing}")
    orbits: dict[str, GaiaOrbit] = {}
    for row in reader:
        if None in row:
            raise PhaseValidationError("Gaia orbit row has extra fields")
        source = _source_token(row[mapping["source_id"]], label="Gaia source_id")
        if source in orbits:
            raise PhaseValidationError("Gaia orbit table repeats a source_id")
        solution_type = str(row[mapping["nss_solution_type"]]).strip()
        if solution_type not in {"SB1", "SB1C"}:
            raise PhaseValidationError("unsupported Gaia orbit solution type")
        period = _float_token(row[mapping["period"]], label="period")
        ref_epoch = _float_token(row[mapping["gaia_ref_epoch"]], label="ref_epoch")
        t_periastron = _float_token(
            row[mapping["t_periastron"]], label="t_periastron"
        )
        k1 = _float_token(
            row[mapping["semi_amplitude_primary"]], label="semi_amplitude_primary"
        )
        assert period is not None and ref_epoch is not None
        assert t_periastron is not None and k1 is not None
        if period <= 0 or k1 <= 0:
            raise PhaseValidationError("period and K1 must be positive")
        eccentricity = _float_token(
            row.get(mapping.get("eccentricity", "")),
            label="eccentricity",
            required=False,
        )
        arg_periastron = _float_token(
            row.get(mapping.get("arg_periastron", "")),
            label="arg_periastron",
            required=False,
        )
        if solution_type == "SB1C":
            eccentricity = 0.0
            arg_periastron = 0.0
        elif eccentricity is None or arg_periastron is None:
            raise PhaseValidationError("SB1 orbit lacks eccentricity or argument")
        assert eccentricity is not None and arg_periastron is not None
        if not 0 <= eccentricity < 1:
            raise PhaseValidationError("Gaia eccentricity is outside [0,1)")
        orbits[source] = GaiaOrbit(
            source_id=source,
            solution_type=solution_type,
            period_days=period,
            ref_epoch_jyear=ref_epoch,
            t_periastron_days=t_periastron,
            eccentricity=eccentricity,
            arg_periastron_deg=arg_periastron,
            semi_amplitude_kms=k1,
        )
    return orbits
