#!/usr/bin/env python3
"""Formal Gaia covariance propagation for exact HOU-COMPACT candidates.

Every source-level input and output is candidate-sensitive and must remain inside the
encrypted capsule. Public summaries expose aggregate counts only. The propagation uses
Gaia's reported Gaussian covariance for the orbital parameters entering the SB1 mass
function, fixes the primary mass to the Gaia FLAME lower bound, and assumes edge-on
inclination. It is a catalogue-uncertainty gate, not a compact-object classification.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
from astropy.table import Table

from hou_compact.gaia_covariance import sb1_mass_parameter_covariance
from hou_compact.reference_covariance import compare_with_nsstools

_EXACT_ID = re.compile(r"^[0-9]{10,20}$")
_MISSING = {"", "--", "nan", "NaN", "null", "None"}
_TRUE = {"1", "true", "yes", "y"}
_G = 6.67430e-11
_M_SUN = 1.98847e30
_DAY = 86400.0
_COVARIANCE_FIELDS = (
    "bit_index",
    "corr_vec",
    "center_of_mass_velocity",
    "center_of_mass_velocity_error",
    "t_periastron_error",
    "arg_periastron_error",
)


class GaiaCovarianceVettingError(RuntimeError):
    """Raised when identity, covariance, or numerical contracts fail closed."""


def _headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise GaiaCovarianceVettingError("table has no header")
    result: dict[str, str] = {}
    for name in fieldnames:
        key = str(name).strip().lower().lstrip("\ufeff")
        if not key or key in result:
            raise GaiaCovarianceVettingError("table has empty or duplicate normalized header")
        result[key] = str(name)
    return result


def _exact_id(value: object, *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not _EXACT_ID.fullmatch(token):
        raise GaiaCovarianceVettingError(f"{label} is not an exact Gaia source identifier")
    return token


def _finite(value: object, *, label: str) -> float:
    token = "" if value is None else str(value).strip()
    if token in _MISSING:
        raise GaiaCovarianceVettingError(f"missing required {label}")
    try:
        result = float(token)
    except ValueError as error:
        raise GaiaCovarianceVettingError(f"{label} is not numeric") from error
    if not math.isfinite(result):
        raise GaiaCovarianceVettingError(f"{label} is not finite")
    return result


def _truth(value: object) -> bool:
    return str(value).strip().lower() in _TRUE


def _table_value(record: object, column: str) -> str:
    value = record[column]  # type: ignore[index]
    return "" if getattr(value, "mask", False) else str(value)


def _load_csv_by_source(
    path: Path,
    *,
    label: str,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        if "source_id" not in mapping:
            raise GaiaCovarianceVettingError(f"{label} lacks source_id")
        fieldnames = list(reader.fieldnames or [])
        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            if None in row:
                raise GaiaCovarianceVettingError(f"{label} row has extra fields")
            source = _exact_id(row[mapping["source_id"]], label=f"{label} source")
            if source in rows:
                raise GaiaCovarianceVettingError(f"{label} repeats a source")
            rows[source] = row
    if not rows:
        raise GaiaCovarianceVettingError(f"{label} is empty")
    return fieldnames, rows


def augment_candidate_covariance_fields(*, gaia_ecsv: Path, candidate_gaia: Path) -> dict[str, Any]:
    """Append exact Gaia covariance/reference fields without changing candidate membership."""

    original_fields, rows = _load_csv_by_source(candidate_gaia, label="candidate Gaia")
    table = Table.read(gaia_ecsv, format="ascii.ecsv")
    available = {str(name).strip().lower(): str(name) for name in table.colnames}
    missing = sorted({"source_id", *_COVARIANCE_FIELDS} - set(available))
    if missing:
        raise GaiaCovarianceVettingError(f"Gaia ECSV lacks covariance fields: {missing}")

    source_records: dict[str, object] = {}
    for record in table:
        source = _exact_id(_table_value(record, available["source_id"]), label="Gaia ECSV source")
        if source not in rows:
            continue
        if source in source_records:
            raise GaiaCovarianceVettingError("Gaia ECSV repeats a candidate source")
        source_records[source] = record
    if set(source_records) != set(rows):
        raise GaiaCovarianceVettingError("Gaia ECSV lacks one or more candidate sources")

    appended = [name for name in _COVARIANCE_FIELDS if name not in _headers(original_fields)]
    fieldnames = original_fields + appended
    for source, row in rows.items():
        record = source_records[source]
        for name in appended:
            row[name] = _table_value(record, available[name])

    temporary = candidate_gaia.with_suffix(candidate_gaia.suffix + ".covariance.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows.values())
    temporary.replace(candidate_gaia)

    return {
        "schema_version": "0.1",
        "candidate_safe": True,
        "candidate_sources": len(rows),
        "fields_appended": len(appended),
        "membership_preserved_exactly": True,
        "claim_boundary": "Exact covariance-field enrichment only; no source is disclosed or re-ranked.",
    }


def _mass_function_solar_array(
    period_days: np.ndarray,
    k1_kms: np.ndarray,
    eccentricity: np.ndarray,
) -> np.ndarray:
    return (
        period_days
        * _DAY
        * (k1_kms * 1000.0) ** 3
        * np.power(1.0 - eccentricity**2, 1.5)
        / (2.0 * math.pi * _G)
        / _M_SUN
    )


def _minimum_companion_mass_array(
    mass_function: np.ndarray,
    primary_mass_solar: float,
) -> np.ndarray:
    values = np.asarray(mass_function, dtype=float)
    if primary_mass_solar <= 0 or np.any(~np.isfinite(values)) or np.any(values < 0):
        raise GaiaCovarianceVettingError("invalid minimum-mass inputs")
    low = np.zeros_like(values)
    high = np.maximum(1.0, values + primary_mass_solar)
    for _ in range(64):
        residual = high**3 / (primary_mass_solar + high) ** 2 - values
        high = np.where(residual < 0, high * 2.0, high)
    if np.any(high > 1e8):
        raise GaiaCovarianceVettingError("companion-mass roots could not be bracketed")
    for _ in range(96):
        middle = (low + high) / 2.0
        residual = middle**3 / (primary_mass_solar + middle) ** 2 - values
        high = np.where(residual >= 0, middle, high)
        low = np.where(residual < 0, middle, low)
    return high


def _source_seed(source_id: str, global_seed: int) -> int:
    digest = hashlib.sha256(f"{global_seed}:{source_id}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def _evaluate_source(
    grow: dict[str, str],
    prow: dict[str, str],
    *,
    draws: int,
    global_seed: int,
    parity_tolerance: float,
) -> dict[str, Any]:
    source = _exact_id(grow.get("source_id"), label="candidate source")
    solution = str(grow.get("nss_solution_type", "")).strip()
    if solution not in {"SB1", "SB1C"}:
        raise GaiaCovarianceVettingError(f"unsupported solution type: {solution!r}")

    parity = compare_with_nsstools(grow)
    if parity.maximum_absolute_difference > parity_tolerance:
        raise GaiaCovarianceVettingError(
            "HOU-COMPACT covariance decode disagrees with nsstools: "
            f"{parity.maximum_absolute_difference}"
        )

    period = _finite(grow.get("period"), label="period")
    k1 = _finite(grow.get("semi_amplitude_primary"), label="semi_amplitude_primary")
    period_error = _finite(grow.get("period_error"), label="period_error")
    k1_error = _finite(
        grow.get("semi_amplitude_primary_error"),
        label="semi_amplitude_primary_error",
    )
    eccentricity = 0.0 if solution == "SB1C" else _finite(
        grow.get("eccentricity"), label="eccentricity"
    )
    eccentricity_error = 0.0 if solution == "SB1C" else _finite(
        grow.get("eccentricity_error"), label="eccentricity_error"
    )
    primary_mass = _finite(grow.get("mass_flame_lower"), label="mass_flame_lower")
    if period <= 0 or k1 <= 0 or period_error < 0 or k1_error < 0 or primary_mass <= 0:
        raise GaiaCovarianceVettingError("non-positive orbit, uncertainty, or primary mass")
    if not 0 <= eccentricity < 1 or eccentricity_error < 0:
        raise GaiaCovarianceVettingError("invalid eccentricity or eccentricity uncertainty")

    covariance = sb1_mass_parameter_covariance(
        solution_type=solution,
        bit_index=grow.get("bit_index"),
        corr_vec=grow.get("corr_vec"),
        period_error=period_error,
        k1_error=k1_error,
        eccentricity_error=eccentricity_error,
    )
    means = {
        "period": period,
        "semi_amplitude_primary": k1,
        "eccentricity": eccentricity,
    }
    mean = np.asarray([means[name] for name in covariance.parameter_names], dtype=float)
    rng = np.random.default_rng(_source_seed(source, global_seed))
    samples = rng.multivariate_normal(
        mean,
        covariance.covariance,
        size=draws,
        check_valid="raise",
        method="eigh",
    )
    sampled = {name: samples[:, index] for index, name in enumerate(covariance.parameter_names)}
    sample_period = sampled["period"]
    sample_k1 = sampled["semi_amplitude_primary"]
    sample_eccentricity = sampled.get("eccentricity", np.zeros(draws, dtype=float))
    physical = (
        np.isfinite(sample_period)
        & np.isfinite(sample_k1)
        & np.isfinite(sample_eccentricity)
        & (sample_period > 0)
        & (sample_k1 > 0)
        & (sample_eccentricity >= 0)
        & (sample_eccentricity < 1)
    )
    accepted = int(np.count_nonzero(physical))
    accepted_fraction = accepted / draws
    if accepted_fraction < 0.5:
        raise GaiaCovarianceVettingError(
            f"physical covariance-draw fraction is too low: {accepted_fraction}"
        )

    f_mass = _mass_function_solar_array(
        sample_period[physical],
        sample_k1[physical],
        sample_eccentricity[physical],
    )
    companion = _minimum_companion_mass_array(f_mass, primary_mass)
    quantiles = {
        "q15_865": float(np.quantile(companion, 0.158655, method="linear")),
        "q2_275": float(np.quantile(companion, 0.02275, method="linear")),
        "q0_135": float(np.quantile(companion, 0.00135, method="linear")),
        "median": float(np.quantile(companion, 0.5, method="linear")),
    }
    strict_phase = _truth(prow.get("strict_phase_supported"))
    nominal_promoted = _truth(prow.get("nominal_strict_phase_mass3"))
    return {
        "source_id": source,
        "gaia_covariance_reference_api": parity.reference_api,
        "gaia_covariance_reference_max_abs_difference": parity.maximum_absolute_difference,
        "gaia_covariance_decoding_mode": covariance.decoding_mode,
        "gaia_covariance_regularized": covariance.regularized,
        "gaia_covariance_raw_vector_length": covariance.raw_vector_length,
        "gaia_covariance_draws_requested": draws,
        "gaia_covariance_draws_physical": accepted,
        "gaia_covariance_physical_draw_fraction": accepted_fraction,
        "minimum_companion_mass_covariance_q15_865_solar": quantiles["q15_865"],
        "minimum_companion_mass_covariance_q2_275_solar": quantiles["q2_275"],
        "minimum_companion_mass_covariance_q0_135_solar": quantiles["q0_135"],
        "minimum_companion_mass_covariance_median_solar": quantiles["median"],
        "probability_minimum_companion_mass_at_least_1_4": float(np.mean(companion >= 1.4)),
        "probability_minimum_companion_mass_at_least_3": float(np.mean(companion >= 3.0)),
        "covariance_q15_865_strict_phase_mass3": bool(strict_phase and quantiles["q15_865"] >= 3),
        "covariance_q2_275_strict_phase_mass3": bool(strict_phase and quantiles["q2_275"] >= 3),
        "covariance_q0_135_strict_phase_mass3": bool(strict_phase and quantiles["q0_135"] >= 3),
        "nominal_promoted_source": nominal_promoted,
    }


def augment_covariance_phase_products(
    *,
    candidate_gaia: Path,
    phase_rows: Path,
    phase_summary: Path,
    draws: int = 200_000,
    global_seed: int = 20260724,
    parity_tolerance: float = 1e-10,
) -> dict[str, Any]:
    """Append formal-covariance mass quantiles and aggregate candidate-safe counts."""

    if draws < 10_000:
        raise ValueError("draws must be at least 10000")
    _, gaia = _load_csv_by_source(candidate_gaia, label="candidate Gaia")
    phase_fields, phase = _load_csv_by_source(phase_rows, label="phase table")
    if set(gaia) != set(phase):
        raise GaiaCovarianceVettingError("candidate Gaia and phase source sets disagree")

    records: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    for source in sorted(phase):
        evaluated = _evaluate_source(
            gaia[source],
            phase[source],
            draws=draws,
            global_seed=global_seed,
            parity_tolerance=parity_tolerance,
        )
        row: dict[str, Any] = dict(phase[source])
        row.update({key: value for key, value in evaluated.items() if key != "source_id"})
        records.append(row)
        evaluations.append(evaluated)

    fields = list(phase_fields)
    for row in records:
        for key in row:
            if key not in fields:
                fields.append(key)
    temporary = phase_rows.with_suffix(phase_rows.suffix + ".covariance.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(records)
    temporary.replace(phase_rows)

    def count(flag: str) -> int:
        return sum(bool(row.get(flag)) for row in evaluations)

    def nominal_survivors(flag: str) -> int:
        return sum(bool(row.get("nominal_promoted_source")) and bool(row.get(flag)) for row in evaluations)

    vetting = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "candidate_sources": len(evaluations),
        "draws_per_source": draws,
        "global_seed": global_seed,
        "dpac_reference_api": "nsstools.NssSource.covmat",
        "dpac_parity_tolerance": parity_tolerance,
        "sources_dpac_covariance_parity_within_tolerance": len(evaluations),
        "sources_covariance_regularized": sum(
            bool(row["gaia_covariance_regularized"]) for row in evaluations
        ),
        "sources_both_strict_phase_and_covariance_q15_865_minimum_mass_at_least_3_solar": count(
            "covariance_q15_865_strict_phase_mass3"
        ),
        "sources_both_strict_phase_and_covariance_q2_275_minimum_mass_at_least_3_solar": count(
            "covariance_q2_275_strict_phase_mass3"
        ),
        "sources_both_strict_phase_and_covariance_q0_135_minimum_mass_at_least_3_solar": count(
            "covariance_q0_135_strict_phase_mass3"
        ),
        "nominal_promoted_sources_surviving_covariance_q15_865_mass": nominal_survivors(
            "covariance_q15_865_strict_phase_mass3"
        ),
        "nominal_promoted_sources_surviving_covariance_q2_275_mass": nominal_survivors(
            "covariance_q2_275_strict_phase_mass3"
        ),
        "nominal_promoted_sources_surviving_covariance_q0_135_mass": nominal_survivors(
            "covariance_q0_135_strict_phase_mass3"
        ),
        "contract": {
            "orbit_uncertainty": "Gaia formal P/K1/e covariance decoded from bit_index and corr_vec",
            "reference_parity": "every candidate compared with nsstools.NssSource.covmat",
            "sampling": "deterministic multivariate-normal draws conditioned on physical P>0, K1>0, 0<=e<1",
            "primary_mass": "Gaia FLAME lower bound held fixed",
            "inclination": "edge-on sin(i)=1",
            "one_sided_lower_quantiles": {
                "one_sigma": 0.158655,
                "two_sigma": 0.02275,
                "three_sigma": 0.00135,
            },
        },
        "claim_boundary": (
            "Formal Gaia covariance propagation is a catalogue-uncertainty triage gate. "
            "It does not include non-Gaussian solution systematics, aliases, stellar-mass "
            "systematics, luminous companions, hierarchy, activity, or independent spectroscopy."
        ),
    }

    summary = json.loads(phase_summary.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or summary.get("candidate_safe") is not True:
        raise GaiaCovarianceVettingError("phase summary is not candidate-safe")
    summary["gaia_covariance_vetting"] = vetting
    phase_summary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return vetting
