#!/usr/bin/env python3
"""Gaia stellar/orbit robustness and simple geometry vetting for HOU-COMPACT.

All source-level inputs and outputs are candidate-sensitive and must remain inside the
encrypted capsule.  The public summary exposes only aggregate threshold counts.  These
checks strengthen or weaken a follow-up case; they do not classify a compact object.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from astropy.table import Table

_EXACT_ID = re.compile(r"^[0-9]{10,20}$")
_G = 6.67430e-11
_M_SUN = 1.98847e30
_R_SUN = 6.957e8
_DAY = 86400.0
_MISSING = {"", "--", "nan", "NaN", "null", "None"}
_TRUE = {"1", "true", "yes", "y"}
_FALSE = {"0", "false", "no", "n"}

_EXTRA_GAIA_FIELDS = [
    "period_error",
    "eccentricity_error",
    "semi_amplitude_primary_error",
    "radius_gspphot",
    "radius_gspphot_lower",
    "radius_gspphot_upper",
    "ruwe",
    "astrometric_gof_al",
    "astrometric_excess_noise",
    "astrometric_excess_noise_sig",
    "duplicated_source",
    "ipd_frac_multi_peak",
    "ipd_frac_odd_win",
    "phot_bp_n_obs",
    "phot_rp_n_obs",
    "phot_bp_n_contaminated_transits",
    "phot_bp_n_blended_transits",
    "phot_rp_n_contaminated_transits",
    "phot_rp_n_blended_transits",
    "phot_bp_rp_excess_factor",
    "rv_n_good_obs_primary",
    "conf_spectro_period",
    "goodness_of_fit",
    "efficiency",
    "significance",
    "flags",
]


class GaiaVettingError(RuntimeError):
    """Raised when candidate identity or numerical contracts are violated."""


def _headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise GaiaVettingError("table has no header")
    result: dict[str, str] = {}
    for name in fieldnames:
        key = str(name).strip().lower().lstrip("\ufeff")
        if not key or key in result:
            raise GaiaVettingError("table has empty or duplicate normalized header")
        result[key] = str(name)
    return result


def _exact_id(value: object, *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not _EXACT_ID.fullmatch(token):
        raise GaiaVettingError(f"{label} is not an exact Gaia source identifier")
    return token


def _finite(value: object) -> float | None:
    token = "" if value is None else str(value).strip()
    if token in _MISSING:
        return None
    try:
        result = float(token)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _positive(value: object) -> float | None:
    result = _finite(value)
    return result if result is not None and result > 0 else None


def _nonnegative(value: object) -> float | None:
    result = _finite(value)
    return result if result is not None and result >= 0 else None


def _optional_bool(value: object) -> bool | None:
    token = "" if value is None else str(value).strip().lower()
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    return None


def _truth(value: object) -> bool:
    return _optional_bool(value) is True


def _table_value(record: object, column: str) -> str:
    value = record[column]  # type: ignore[index]
    return "" if getattr(value, "mask", False) else str(value)


def augment_candidate_gaia(*, gaia_ecsv: Path, candidate_gaia: Path) -> dict[str, int]:
    """Append frozen Gaia quality/error/radius fields to exact candidate rows."""

    with candidate_gaia.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        if "source_id" not in mapping:
            raise GaiaVettingError("candidate Gaia table lacks source_id")
        original_fields = list(reader.fieldnames or [])
        rows = list(reader)
    candidate_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if None in row:
            raise GaiaVettingError("candidate Gaia row has extra fields")
        source = _exact_id(row[mapping["source_id"]], label="candidate source")
        if source in seen:
            raise GaiaVettingError("candidate Gaia table repeats a source")
        seen.add(source)
        candidate_ids.append(source)

    table = Table.read(gaia_ecsv, format="ascii.ecsv")
    available = {str(name).lower(): str(name) for name in table.colnames}
    if "source_id" not in available:
        raise GaiaVettingError("Gaia ECSV lacks source_id")
    source_records: dict[str, object] = {}
    for record in table:
        source = _exact_id(record[available["source_id"]], label="Gaia ECSV source")
        if source not in seen:
            continue
        if source in source_records:
            raise GaiaVettingError("Gaia ECSV repeats a candidate source")
        source_records[source] = record
    if set(source_records) != seen:
        raise GaiaVettingError("Gaia ECSV lacks one or more candidate sources")

    appended = [name for name in _EXTRA_GAIA_FIELDS if name not in mapping]
    fieldnames = original_fields + appended
    for row, source in zip(rows, candidate_ids):
        record = source_records[source]
        for name in appended:
            column = available.get(name)
            row[name] = "" if column is None else _table_value(record, column)

    temporary = candidate_gaia.with_suffix(candidate_gaia.suffix + ".vetting.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(candidate_gaia)
    return {
        "candidate_sources": len(rows),
        "fields_appended": len(appended),
        "requested_extra_fields": len(_EXTRA_GAIA_FIELDS),
    }


def mass_function_solar(period_days: float, k1_kms: float, eccentricity: float) -> float:
    if period_days <= 0 or k1_kms < 0 or not 0 <= eccentricity < 1:
        raise ValueError("invalid orbit for mass function")
    value = (
        period_days
        * _DAY
        * (k1_kms * 1000.0) ** 3
        * (1.0 - eccentricity**2) ** 1.5
        / (2.0 * math.pi * _G)
    )
    return value / _M_SUN


def minimum_companion_mass(f_mass: float, primary_mass: float) -> float:
    if f_mass < 0 or primary_mass <= 0:
        raise ValueError("invalid mass-function inputs")
    if f_mass == 0:
        return 0.0
    low = 0.0
    high = max(1.0, f_mass + primary_mass)

    def equation(m2: float) -> float:
        return m2**3 / (primary_mass + m2) ** 2 - f_mass

    while equation(high) < 0:
        high *= 2.0
        if high > 1e7:
            raise GaiaVettingError("minimum-mass root could not be bracketed")
    for _ in range(180):
        middle = (low + high) / 2.0
        if equation(middle) >= 0:
            high = middle
        else:
            low = middle
    return high


def _roche_fill_proxy(
    *,
    period_days: float,
    eccentricity: float,
    primary_mass: float,
    companion_mass: float,
    primary_radius: float,
) -> float:
    if (
        period_days <= 0
        or not 0 <= eccentricity < 1
        or primary_mass <= 0
        or companion_mass <= 0
        or primary_radius <= 0
    ):
        raise ValueError("invalid Roche-geometry inputs")
    total_mass = (primary_mass + companion_mass) * _M_SUN
    axis_m = (_G * total_mass * (period_days * _DAY) ** 2 / (4.0 * math.pi**2)) ** (
        1.0 / 3.0
    )
    periastron_rsun = axis_m * (1.0 - eccentricity) / _R_SUN
    q = primary_mass / companion_mass
    q13 = q ** (1.0 / 3.0)
    q23 = q13**2
    roche_fraction = 0.49 * q23 / (0.6 * q23 + math.log1p(q13))
    return primary_radius / (periastron_rsun * roche_fraction)


def _load_csv_by_source(path: Path, *, label: str) -> tuple[list[str], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        if "source_id" not in mapping:
            raise GaiaVettingError(f"{label} lacks source_id")
        fieldnames = list(reader.fieldnames or [])
        result: dict[str, dict[str, str]] = {}
        for row in reader:
            if None in row:
                raise GaiaVettingError(f"{label} row has extra fields")
            source = _exact_id(row[mapping["source_id"]], label=f"{label} source")
            if source in result:
                raise GaiaVettingError(f"{label} repeats a source")
            result[source] = row
    return fieldnames, result


def _sum_positive(row: dict[str, str], names: tuple[str, ...]) -> bool | None:
    values = [_nonnegative(row.get(name)) for name in names]
    known = [value for value in values if value is not None]
    return None if not known else any(value > 0 for value in known)


def augment_phase_products(
    *,
    candidate_gaia: Path,
    phase_rows: Path,
    phase_summary: Path,
) -> dict[str, Any]:
    """Add one-sigma mass, Roche geometry, and direct Gaia quality diagnostics."""

    gaia_fields, gaia = _load_csv_by_source(candidate_gaia, label="candidate Gaia")
    phase_fields, phase = _load_csv_by_source(phase_rows, label="phase table")
    if set(gaia) != set(phase):
        raise GaiaVettingError("candidate Gaia and phase source sets disagree")

    records: list[dict[str, Any]] = []
    for source in sorted(phase):
        grow = gaia[source]
        prow: dict[str, Any] = dict(phase[source])
        period = _positive(grow.get("period"))
        period_error = _nonnegative(grow.get("period_error"))
        k1 = _positive(grow.get("semi_amplitude_primary"))
        k1_error = _nonnegative(grow.get("semi_amplitude_primary_error"))
        eccentricity = _nonnegative(grow.get("eccentricity"))
        if str(grow.get("nss_solution_type", "")).strip() == "SB1C":
            eccentricity = 0.0
            eccentricity_error = 0.0
        else:
            eccentricity_error = _nonnegative(grow.get("eccentricity_error"))
        primary_nominal = _positive(grow.get("mass_flame"))
        primary_lower = _positive(grow.get("mass_flame_lower")) or primary_nominal
        radius_nominal = _positive(grow.get("radius_gspphot"))
        radius_upper = _positive(grow.get("radius_gspphot_upper")) or radius_nominal
        nominal_minimum = _positive(
            prow.get("minimum_companion_mass_using_primary_lower_solar")
        )
        strict_phase = _truth(prow.get("strict_phase_supported"))

        f_lower: float | None = None
        m2_lower: float | None = None
        period_low: float | None = None
        eccentricity_high: float | None = None
        if (
            period is not None
            and period_error is not None
            and k1 is not None
            and k1_error is not None
            and eccentricity is not None
            and eccentricity_error is not None
            and primary_lower is not None
        ):
            period_low = max(period - period_error, math.ulp(1.0))
            k1_low = max(k1 - k1_error, 0.0)
            eccentricity_high = min(eccentricity + eccentricity_error, 0.999999)
            f_lower = mass_function_solar(period_low, k1_low, eccentricity_high)
            m2_lower = minimum_companion_mass(f_lower, primary_lower)

        nominal_fill: float | None = None
        stressed_fill: float | None = None
        if (
            period is not None
            and eccentricity is not None
            and primary_lower is not None
            and nominal_minimum is not None
            and radius_nominal is not None
        ):
            nominal_fill = _roche_fill_proxy(
                period_days=period,
                eccentricity=eccentricity,
                primary_mass=primary_lower,
                companion_mass=nominal_minimum,
                primary_radius=radius_nominal,
            )
        if (
            period_low is not None
            and eccentricity_high is not None
            and primary_lower is not None
            and m2_lower is not None
            and m2_lower > 0
            and radius_upper is not None
        ):
            stressed_fill = _roche_fill_proxy(
                period_days=period_low,
                eccentricity=eccentricity_high,
                primary_mass=primary_lower,
                companion_mass=m2_lower,
                primary_radius=radius_upper,
            )

        duplicated = _optional_bool(grow.get("duplicated_source"))
        any_contaminated = _sum_positive(
            grow,
            (
                "phot_bp_n_contaminated_transits",
                "phot_rp_n_contaminated_transits",
            ),
        )
        any_blended = _sum_positive(
            grow,
            ("phot_bp_n_blended_transits", "phot_rp_n_blended_transits"),
        )
        ipd_multi = _nonnegative(grow.get("ipd_frac_multi_peak"))
        ipd_odd = _nonnegative(grow.get("ipd_frac_odd_win"))

        nominal_promoted = bool(strict_phase and nominal_minimum is not None and nominal_minimum >= 3)
        robust_promoted = bool(strict_phase and m2_lower is not None and m2_lower >= 3)
        roche_safe = stressed_fill is not None and stressed_fill < 0.8
        duplicate_free = duplicated is False
        basic_survivor = bool(robust_promoted and roche_safe and duplicate_free)

        prow.update(
            {
                "mass_function_1sigma_lower_solar": f_lower,
                "minimum_companion_mass_1sigma_lower_solar": m2_lower,
                "primary_roche_fill_nominal_proxy": nominal_fill,
                "primary_roche_fill_1sigma_stress_proxy": stressed_fill,
                "gaia_duplicated_source": duplicated,
                "gaia_any_contaminated_transit": any_contaminated,
                "gaia_any_blended_transit": any_blended,
                "gaia_ipd_multi_peak_nonzero": None if ipd_multi is None else ipd_multi > 0,
                "gaia_ipd_odd_window_nonzero": None if ipd_odd is None else ipd_odd > 0,
                "nominal_strict_phase_mass3": nominal_promoted,
                "robust_1sigma_strict_phase_mass3": robust_promoted,
                "stressed_roche_fill_below_0_8": roche_safe,
                "gaia_duplicate_free": duplicate_free,
                "basic_mass_geometry_duplicate_vetting_survivor": basic_survivor,
            }
        )
        records.append(prow)

    fields = sorted({key for row in records for key in row})
    temporary = phase_rows.with_suffix(phase_rows.suffix + ".vetting.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(records)
    temporary.replace(phase_rows)

    def count(name: str, expected: object = True) -> int:
        return sum(row.get(name) == expected for row in records)

    vetting = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "candidate_sources": len(records),
        "sources_with_complete_orbit_1sigma_mass_inputs": sum(
            row.get("minimum_companion_mass_1sigma_lower_solar") not in {None, ""}
            for row in records
        ),
        "sources_1sigma_minimum_companion_mass_at_least_1_4_solar": sum(
            row.get("minimum_companion_mass_1sigma_lower_solar") is not None
            and float(row["minimum_companion_mass_1sigma_lower_solar"]) >= 1.4
            for row in records
        ),
        "sources_1sigma_minimum_companion_mass_at_least_3_solar": sum(
            row.get("minimum_companion_mass_1sigma_lower_solar") is not None
            and float(row["minimum_companion_mass_1sigma_lower_solar"]) >= 3
            for row in records
        ),
        "sources_both_strict_phase_and_1sigma_minimum_mass_at_least_3_solar": count(
            "robust_1sigma_strict_phase_mass3"
        ),
        "sources_with_stressed_roche_geometry": sum(
            row.get("primary_roche_fill_1sigma_stress_proxy") not in {None, ""}
            for row in records
        ),
        "sources_stressed_roche_fill_at_least_0_8": sum(
            row.get("primary_roche_fill_1sigma_stress_proxy") is not None
            and float(row["primary_roche_fill_1sigma_stress_proxy"]) >= 0.8
            for row in records
        ),
        "sources_duplicated_source_true": count("gaia_duplicated_source"),
        "sources_any_bp_rp_contaminated_transit": count(
            "gaia_any_contaminated_transit"
        ),
        "sources_any_bp_rp_blended_transit": count("gaia_any_blended_transit"),
        "sources_ipd_multi_peak_nonzero": count("gaia_ipd_multi_peak_nonzero"),
        "sources_ipd_odd_window_nonzero": count("gaia_ipd_odd_window_nonzero"),
        "nominal_strict_phase_mass3_sources": count("nominal_strict_phase_mass3"),
        "nominal_promoted_sources_surviving_1sigma_mass": sum(
            bool(row.get("nominal_strict_phase_mass3"))
            and bool(row.get("robust_1sigma_strict_phase_mass3"))
            for row in records
        ),
        "nominal_promoted_sources_with_stressed_roche_fill_below_0_8": sum(
            bool(row.get("nominal_strict_phase_mass3"))
            and bool(row.get("stressed_roche_fill_below_0_8"))
            for row in records
        ),
        "nominal_promoted_sources_duplicate_free": sum(
            bool(row.get("nominal_strict_phase_mass3"))
            and bool(row.get("gaia_duplicate_free"))
            for row in records
        ),
        "basic_mass_geometry_duplicate_vetting_survivors": count(
            "basic_mass_geometry_duplicate_vetting_survivor"
        ),
        "contracts": {
            "one_sigma_mass_lower": (
                "P-1sigma, K1-1sigma, e+1sigma, and Gaia FLAME lower primary mass; "
                "edge-on sin(i)=1"
            ),
            "stressed_roche_proxy": (
                "P-1sigma, e+1sigma, Gaia FLAME lower primary mass, Gaia radius upper "
                "bound, and one-sigma lower companion mass"
            ),
            "roche_warning_threshold": 0.8,
            "gaia_blend_fields": (
                "duplicated_source plus BP/RP contaminated/blended-transit counts and "
                "IPD multi-peak/odd-window fractions; only duplicated_source is used in "
                "the basic survivor gate"
            ),
        },
        "claim_boundary": (
            "One-sigma mass, Roche geometry, and Gaia image/photometry diagnostics are "
            "triage gates only. They do not establish a dark companion, exclude a luminous "
            "companion or hierarchy, or replace independent spectroscopy and stellar modelling."
        ),
    }

    summary = json.loads(phase_summary.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or summary.get("candidate_safe") is not True:
        raise GaiaVettingError("phase summary is not a candidate-safe object")
    contract = summary.get("contract")
    if isinstance(contract, dict):
        contract["exact_time"] = (
            "12/12 exact-OBSID first-party FITS DATE-OBS median UTC times; MEC retained "
            "as a diagnostic only"
        )
    summary["gaia_stellar_orbit_vetting"] = vetting
    phase_summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return vetting
