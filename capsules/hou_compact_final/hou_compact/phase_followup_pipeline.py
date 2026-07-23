#!/usr/bin/env python3
"""Prepare and validate encrypted follow-up for conservative LAMOST RV candidates.

Source identities and per-source products are candidate-sensitive. Public summaries
contain aggregate counts only. A phase match or large nominal minimum mass is a
follow-up statistic, never a compact-object classification.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
from pathlib import Path
from typing import Any

from astropy.table import Table

from gaia_rv_phase_validation import load_gaia_orbits
from gaia_rv_phase_validation_timed import load_exact_timed_rv, validate_timed_phase
from lamost_multi_epoch_time import extract_exact_times

_EXACT_ID = re.compile(r"^[0-9]{10,20}$")
_EXACT_OBSID = re.compile(r"^[0-9]+$")
_TRUE = {"1", "true", "yes", "y"}
_G = 6.67430e-11
_M_SUN = 1.98847e30
_DAY = 86400.0


class FollowupError(RuntimeError):
    pass


def _headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise FollowupError("table has no header")
    result: dict[str, str] = {}
    for name in fieldnames:
        key = str(name).strip().lower().lstrip("\ufeff")
        if not key or key in result:
            raise FollowupError("table has empty or duplicate normalized header")
        result[key] = str(name)
    return result


def _exact(value: object, pattern: re.Pattern[str], *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not pattern.fullmatch(token):
        raise FollowupError(f"{label} is not exact integer text")
    return token


def _truth(value: object) -> bool:
    return str(value).strip().lower() in _TRUE


def _finite(value: object) -> float | None:
    token = "" if value is None else str(value).strip()
    if token in {"", "--", "nan", "NaN", "null", "None"}:
        return None
    try:
        result = float(token)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def prepare_candidates(
    *,
    gaia_ecsv: Path,
    exact_rv: Path,
    source_metrics: Path,
    overlap: Path,
    candidate_gaia: Path,
    candidate_rv: Path,
    candidate_overlap: Path,
    summary_path: Path,
) -> dict[str, Any]:
    candidates: set[str] = set()
    metrics_rows: dict[str, dict[str, str]] = {}
    with source_metrics.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        required = {"dr3_source_id", "joint_delta20_sigma5_floor", "distinct_rv_nights"}
        missing = sorted(required - set(mapping))
        if missing:
            raise FollowupError(f"source metrics missing columns: {missing}")
        for row in reader:
            if None in row:
                raise FollowupError("source metrics row has extra fields")
            source = _exact(row[mapping["dr3_source_id"]], _EXACT_ID, label="metric source")
            if source in metrics_rows:
                raise FollowupError("source metrics repeats a source")
            metrics_rows[source] = row
            if _truth(row[mapping["joint_delta20_sigma5_floor"]]):
                candidates.add(source)
    if not candidates:
        raise FollowupError("no conservative RV candidates were selected")

    rv_rows: list[dict[str, str]] = []
    rv_obsids: set[str] = set()
    with exact_rv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        required = {"obsid", "hou_compact_dr3_source_id", "rv", "rv_err"}
        missing = sorted(required - set(mapping))
        if missing:
            raise FollowupError(f"exact RV table missing columns: {missing}")
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            source = _exact(
                row[mapping["hou_compact_dr3_source_id"]],
                _EXACT_ID,
                label="RV source",
            )
            if source not in candidates:
                continue
            obsid = _exact(row[mapping["obsid"]], _EXACT_OBSID, label="RV obsid")
            if obsid in rv_obsids:
                raise FollowupError("candidate RV table repeats an obsid")
            rv_obsids.add(obsid)
            rv_rows.append(row)
    if {row[_headers(fieldnames)["hou_compact_dr3_source_id"]] for row in rv_rows} != candidates:
        raise FollowupError("not every conservative candidate has an exact RV row")
    candidate_rv.parent.mkdir(parents=True, exist_ok=True)
    with candidate_rv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rv_rows)

    overlap_rows: list[dict[str, str]] = []
    with overlap.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        required = {"obsid", "hou_compact_dr3_source_id", "hou_compact_dr2_source_id"}
        missing = sorted(required - set(mapping))
        if missing:
            raise FollowupError(f"overlap table missing columns: {missing}")
        overlap_fields = list(reader.fieldnames or [])
        seen: set[str] = set()
        for row in reader:
            obsid = _exact(row[mapping["obsid"]], _EXACT_OBSID, label="overlap obsid")
            if obsid not in rv_obsids:
                continue
            source = _exact(
                row[mapping["hou_compact_dr3_source_id"]],
                _EXACT_ID,
                label="overlap source",
            )
            if source not in candidates:
                raise FollowupError("candidate obsid maps to a non-candidate source")
            if obsid in seen:
                raise FollowupError("candidate overlap repeats an obsid")
            seen.add(obsid)
            overlap_rows.append(row)
    if seen != rv_obsids:
        raise FollowupError("candidate overlap and exact RV obsids disagree")
    candidate_overlap.parent.mkdir(parents=True, exist_ok=True)
    with candidate_overlap.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=overlap_fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(overlap_rows)

    table = Table.read(gaia_ecsv, format="ascii.ecsv")
    available = {str(name).lower(): str(name) for name in table.colnames}
    gaia_fields = [
        "source_id",
        "nss_solution_type",
        "period",
        "gaia_ref_epoch",
        "t_periastron",
        "eccentricity",
        "arg_periastron",
        "semi_amplitude_primary",
        "mass_flame",
        "mass_flame_lower",
        "mass_flame_upper",
        "flags_flame",
    ]
    required_gaia = set(gaia_fields[:8])
    missing = sorted(required_gaia - set(available))
    if missing:
        raise FollowupError(f"Gaia seed missing orbit columns: {missing}")
    gaia_rows: list[dict[str, str]] = []
    found: set[str] = set()
    for record in table:
        source = _exact(record[available["source_id"]], _EXACT_ID, label="Gaia source")
        if source not in candidates:
            continue
        if source in found:
            raise FollowupError("Gaia seed repeats a conservative candidate")
        found.add(source)
        output: dict[str, str] = {}
        for name in gaia_fields:
            column = available.get(name)
            if column is None:
                output[name] = ""
                continue
            value = record[column]
            output[name] = "" if getattr(value, "mask", False) else str(value)
        gaia_rows.append(output)
    if found != candidates:
        raise FollowupError("Gaia seed lacks one or more conservative candidates")
    candidate_gaia.parent.mkdir(parents=True, exist_ok=True)
    with candidate_gaia.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=gaia_fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(sorted(gaia_rows, key=lambda row: row["source_id"]))

    summary = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "conservative_candidate_count": len(candidates),
        "candidate_exact_rv_rows": len(rv_rows),
        "candidate_exact_obsids": len(rv_obsids),
        "candidates_with_at_least_3_rv_nights": sum(
            int(metrics_rows[source]["distinct_rv_nights"]) >= 3 for source in candidates
        ),
        "claim_boundary": (
            "Candidate extraction only. No source identity, obsid, RV value, orbit, mass, "
            "or compact-object classification is disclosed."
        ),
    }
    _write_json(summary_path, summary)
    return summary


def extract_times_from_gzip(
    *, expected: Path, catalog_gz: Path, output: Path, receipt: Path
) -> dict[str, object]:
    with gzip.open(catalog_gz, "rt", encoding="utf-8-sig", newline="") as stream:
        return extract_exact_times(
            expected_path=expected,
            multi_epoch_stream=stream,
            output_path=output,
            receipt_path=receipt,
            checkpoint_every_rows=100_000,
        )


def mass_function_solar(period_days: float, k1_kms: float, eccentricity: float) -> float:
    if period_days <= 0 or k1_kms <= 0 or not 0 <= eccentricity < 1:
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
    if f_mass <= 0 or primary_mass <= 0:
        raise ValueError("mass function and primary mass must be positive")
    low = 0.0
    high = max(1.0, f_mass + primary_mass)

    def equation(m2: float) -> float:
        return m2**3 / (primary_mass + m2) ** 2 - f_mass

    while equation(high) < 0:
        high *= 2.0
        if high > 1e5:
            raise FollowupError("minimum-mass root could not be bracketed")
    for _ in range(160):
        middle = (low + high) / 2.0
        if equation(middle) >= 0:
            high = middle
        else:
            low = middle
    return high


def validate_followup(
    *, gaia_path: Path, rv_path: Path, time_path: Path, source_output: Path, summary_output: Path
) -> dict[str, Any]:
    orbits = load_gaia_orbits(gaia_path)
    timed = load_exact_timed_rv(rv_path=rv_path, time_path=time_path)
    gaia_mass: dict[str, tuple[float | None, float | None, float | None]] = {}
    with gaia_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        for row in reader:
            source = _exact(row[mapping["source_id"]], _EXACT_ID, label="Gaia mass source")
            gaia_mass[source] = (
                _finite(row.get(mapping.get("mass_flame", ""))),
                _finite(row.get(mapping.get("mass_flame_lower", ""))),
                _finite(row.get(mapping.get("mass_flame_upper", ""))),
            )

    rows: list[dict[str, Any]] = []
    for source, orbit in sorted(orbits.items()):
        points = timed.get(source, [])
        phase = validate_timed_phase(orbit, points, systematic_floor_kms=5.0)
        nominal_mass, lower_mass, upper_mass = gaia_mass.get(source, (None, None, None))
        primary_for_lower_bound = lower_mass if lower_mass and lower_mass > 0 else nominal_mass
        f_mass = mass_function_solar(
            orbit.period_days, orbit.semi_amplitude_kms, orbit.eccentricity
        )
        min_mass = (
            minimum_companion_mass(f_mass, primary_for_lower_bound)
            if primary_for_lower_bound and primary_for_lower_bound > 0
            else None
        )
        rows.append(
            {
                "source_id": source,
                "solution_type": orbit.solution_type,
                "period_days": orbit.period_days,
                "semi_amplitude_primary_kms": orbit.semi_amplitude_kms,
                **phase,
                "mass_function_solar": f_mass,
                "primary_mass_nominal_solar": nominal_mass,
                "primary_mass_lower_solar": lower_mass,
                "primary_mass_upper_solar": upper_mass,
                "minimum_companion_mass_using_primary_lower_solar": min_mass,
            }
        )
    fieldnames = sorted({key for row in rows for key in row}) if rows else ["source_id"]
    source_output.parent.mkdir(parents=True, exist_ok=True)
    with source_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)

    def count(predicate) -> int:
        return sum(1 for row in rows if predicate(row))

    summary = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "candidate_orbit_count": len(orbits),
        "candidate_sources_with_exact_time_rv": len(timed),
        "sources_phase_tested": count(lambda row: bool(row.get("phase_test_available"))),
        "sources_with_at_least_3_exact_time_epochs": count(
            lambda row: int(row.get("rv_epochs_with_exact_time", 0)) >= 3
        ),
        "sources_gaia_phase_better_delta_chi2_9": count(
            lambda row: float(row.get("delta_chi2_gaia_vs_constant", -math.inf)) >= 9
        ),
        "sources_strict_phase_supported": count(
            lambda row: bool(row.get("strict_phase_supported"))
        ),
        "sources_mass_function_at_least_1_solar": count(
            lambda row: float(row["mass_function_solar"]) >= 1
        ),
        "sources_mass_function_at_least_3_solar": count(
            lambda row: float(row["mass_function_solar"]) >= 3
        ),
        "sources_minimum_companion_mass_at_least_1_4_solar": count(
            lambda row: row.get("minimum_companion_mass_using_primary_lower_solar") is not None
            and float(row["minimum_companion_mass_using_primary_lower_solar"]) >= 1.4
        ),
        "sources_minimum_companion_mass_at_least_3_solar": count(
            lambda row: row.get("minimum_companion_mass_using_primary_lower_solar") is not None
            and float(row["minimum_companion_mass_using_primary_lower_solar"]) >= 3
        ),
        "sources_both_strict_phase_and_minimum_mass_at_least_3_solar": count(
            lambda row: bool(row.get("strict_phase_supported"))
            and row.get("minimum_companion_mass_using_primary_lower_solar") is not None
            and float(row["minimum_companion_mass_using_primary_lower_solar"]) >= 3
        ),
        "contract": {
            "exact_time": "12/12 exact obsid times from UTC-corrected MEC plus FITS DATE-OBS",
            "rv_systematic_floor_kms_per_epoch": 5,
            "strict_phase_minimum_epochs": 3,
            "minimum_mass_inclination_assumption": "sin(i)=1 edge-on",
            "primary_mass_for_minimum": "Gaia FLAME lower bound, nominal fallback",
            "mass_values_are_nominal_triage_only": True,
        },
        "claim_boundary": (
            "Phase agreement and nominal minimum mass are follow-up statistics only. "
            "They do not establish a black hole, neutron star, compact object, or secure binary."
        ),
    }
    _write_json(summary_output, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--gaia-ecsv", type=Path, required=True)
    prepare.add_argument("--exact-rv", type=Path, required=True)
    prepare.add_argument("--source-metrics", type=Path, required=True)
    prepare.add_argument("--overlap", type=Path, required=True)
    prepare.add_argument("--candidate-gaia", type=Path, required=True)
    prepare.add_argument("--candidate-rv", type=Path, required=True)
    prepare.add_argument("--candidate-overlap", type=Path, required=True)
    prepare.add_argument("--summary", type=Path, required=True)
    times = sub.add_parser("times")
    times.add_argument("--expected", type=Path, required=True)
    times.add_argument("--catalog-gz", type=Path, required=True)
    times.add_argument("--output", type=Path, required=True)
    times.add_argument("--receipt", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--gaia", type=Path, required=True)
    validate.add_argument("--rv", type=Path, required=True)
    validate.add_argument("--times", type=Path, required=True)
    validate.add_argument("--source-output", type=Path, required=True)
    validate.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_candidates(
            gaia_ecsv=args.gaia_ecsv,
            exact_rv=args.exact_rv,
            source_metrics=args.source_metrics,
            overlap=args.overlap,
            candidate_gaia=args.candidate_gaia,
            candidate_rv=args.candidate_rv,
            candidate_overlap=args.candidate_overlap,
            summary_path=args.summary,
        )
    elif args.command == "times":
        result = extract_times_from_gzip(
            expected=args.expected,
            catalog_gz=args.catalog_gz,
            output=args.output,
            receipt=args.receipt,
        )
    else:
        result = validate_followup(
            gaia_path=args.gaia,
            rv_path=args.rv,
            time_path=args.times,
            source_output=args.source_output,
            summary_output=args.summary_output,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
