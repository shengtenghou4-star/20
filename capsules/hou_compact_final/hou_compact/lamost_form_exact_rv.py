#!/usr/bin/env python3
"""Exact-obsid private analysis for first-party LAMOST form RV rows.

The public form client validates that every returned row belongs to the requested
obsid batch. This stage independently revalidates identity against the verified LRS
overlap, applies fail-closed spectrum/RV quality gates, reduces repeated same-night
measurements conservatively, and computes same-pair RV variability. All source-level
outputs are candidate-sensitive and must be encrypted.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

_EXACT_OBSID = re.compile(r"^[0-9]+$")
_EXACT_SOURCE = re.compile(r"^[0-9]{10,20}$")
_INTEGRAL_DECIMAL = re.compile(r"^[+-]?[0-9]+(?:\.0*)?$")
_OBSID_ALIASES = ("obsid", "obs_id")
_DR2_ALIASES = ("hou_compact_dr2_source_id",)
_DR3_ALIASES = ("hou_compact_dr3_source_id",)
_NIGHT_ALIASES = ("lmjd", "mjd", "obsdate")
_RV_ALIASES = ("rv", "radial_velocity")
_RV_ERR_ALIASES = ("rv_err", "radial_velocity_error", "radial_velocity_err")


class FormRvError(RuntimeError):
    """Raised when exact identity, spectrum quality, or RV contracts fail."""


@dataclass(frozen=True)
class ExpectedSpectrum:
    obsid: str
    dr2_source_id: str
    dr3_source_id: str
    independent_night: str


@dataclass(frozen=True)
class RVMeasurement:
    obsid: str
    source_id: str
    night: str
    rv: Decimal
    rv_err: Decimal


def _headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise FormRvError("table has no header")
    mapping: dict[str, str] = {}
    for original in fieldnames:
        normalized = str(original).strip().lower().lstrip("\ufeff")
        if not normalized:
            raise FormRvError("table contains an empty header")
        if normalized in mapping:
            raise FormRvError(f"duplicate normalized header {normalized!r}")
        mapping[normalized] = str(original)
    return mapping


def _resolve(mapping: dict[str, str], aliases: tuple[str, ...], label: str) -> str:
    matches = [mapping[name] for name in aliases if name in mapping]
    if len(matches) != 1:
        raise FormRvError(
            f"expected exactly one {label} column from {aliases!r}; found {matches!r}"
        )
    return matches[0]


def _exact(value: object, pattern: re.Pattern[str], *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not pattern.fullmatch(token):
        raise FormRvError(f"{label} is not an exact integer token")
    return token


def _decimal(value: object, *, label: str) -> Decimal:
    token = "" if value is None else str(value)
    if not token or token != token.strip():
        raise FormRvError(f"{label} is missing or contains whitespace")
    try:
        result = Decimal(token)
    except InvalidOperation as error:
        raise FormRvError(f"{label} is not decimal") from error
    if not result.is_finite():
        raise FormRvError(f"{label} is not finite")
    return result


def _integral_decimal(value: object, *, label: str) -> int:
    token = "" if value is None else str(value)
    if token != token.strip() or not _INTEGRAL_DECIMAL.fullmatch(token):
        raise FormRvError(f"{label} is not exact integral decimal text")
    value_decimal = Decimal(token)
    if not value_decimal.is_finite() or value_decimal != value_decimal.to_integral_value():
        raise FormRvError(f"{label} is not an exact integer value")
    return int(value_decimal)


def _optional_decimal(value: object) -> Decimal | None:
    token = "" if value is None else str(value).strip()
    if token in {"", "--", "nan", "NaN", "null", "None"}:
        return None
    try:
        parsed = Decimal(token)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _independent_night(row: dict[str, str], mapping: dict[str, str]) -> str:
    matches = [mapping[name] for name in _NIGHT_ALIASES if name in mapping]
    if not matches:
        raise FormRvError("verified overlap has no independent-night field")
    column = matches[0]
    value = str(row.get(column, ""))
    if not value or value != value.strip():
        raise FormRvError("verified overlap row has missing or unsafe night value")
    if column.strip().lower() == "obsdate":
        night = value[:10]
    else:
        night = value.split(".", 1)[0]
    if not night:
        raise FormRvError("independent-night normalization produced an empty value")
    return night


def load_verified_overlap(path: Path) -> dict[str, ExpectedSpectrum]:
    if not path.exists() or path.stat().st_size == 0:
        raise FormRvError("verified LRS overlap is missing or empty")
    expected: dict[str, ExpectedSpectrum] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        obsid_column = _resolve(mapping, _OBSID_ALIASES, "overlap obsid")
        dr2_column = _resolve(mapping, _DR2_ALIASES, "derived DR2 source")
        dr3_column = _resolve(mapping, _DR3_ALIASES, "derived DR3 source")
        for row in reader:
            if None in row:
                raise FormRvError("verified overlap row has extra fields")
            obsid = _exact(row.get(obsid_column), _EXACT_OBSID, label="overlap obsid")
            if obsid in expected:
                raise FormRvError("verified overlap repeats an obsid")
            expected[obsid] = ExpectedSpectrum(
                obsid=obsid,
                dr2_source_id=_exact(
                    row.get(dr2_column), _EXACT_SOURCE, label="DR2 source"
                ),
                dr3_source_id=_exact(
                    row.get(dr3_column), _EXACT_SOURCE, label="DR3 source"
                ),
                independent_night=_independent_night(row, mapping),
            )
    if not expected:
        raise FormRvError("verified overlap contains no spectra")
    return expected


def _reduce_night(values: list[RVMeasurement]) -> tuple[Decimal, Decimal]:
    best = min(values, key=lambda item: item.rv_err)
    if len(values) == 1:
        return best.rv, best.rv_err
    observed = [item.rv for item in values]
    half_range = (max(observed) - min(observed)) / Decimal(2)
    return best.rv, max(best.rv_err, half_range)


def _source_metrics(
    measurements: list[RVMeasurement],
    *,
    systematic_floor_kms: Decimal,
) -> dict[str, object]:
    by_night: dict[str, list[RVMeasurement]] = defaultdict(list)
    for measurement in measurements:
        by_night[measurement.night].append(measurement)
    reduced = [
        (night, *_reduce_night(values)) for night, values in sorted(by_night.items())
    ]
    maximum_delta = Decimal(0)
    maximum_formal_sigma = Decimal(0)
    maximum_floor_sigma = Decimal(0)
    joint20_formal = False
    joint20_floor = False
    joint50_floor = False
    joint100_floor = False
    floor_variance = Decimal(2) * systematic_floor_kms * systematic_floor_kms
    for index, (_, rv_a, err_a) in enumerate(reduced):
        for _, rv_b, err_b in reduced[index + 1 :]:
            delta = abs(rv_a - rv_b)
            formal_denominator = (err_a * err_a + err_b * err_b).sqrt()
            floor_denominator = (
                err_a * err_a + err_b * err_b + floor_variance
            ).sqrt()
            formal_sigma = delta / formal_denominator if formal_denominator else Decimal(0)
            floor_sigma = delta / floor_denominator if floor_denominator else Decimal(0)
            maximum_delta = max(maximum_delta, delta)
            maximum_formal_sigma = max(maximum_formal_sigma, formal_sigma)
            maximum_floor_sigma = max(maximum_floor_sigma, floor_sigma)
            joint20_formal |= delta >= Decimal("20") and formal_sigma >= Decimal("5")
            joint20_floor |= delta >= Decimal("20") and floor_sigma >= Decimal("5")
            joint50_floor |= delta >= Decimal("50") and floor_sigma >= Decimal("5")
            joint100_floor |= delta >= Decimal("100") and floor_sigma >= Decimal("5")
    return {
        "valid_rv_rows": len(measurements),
        "distinct_rv_nights": len(reduced),
        "repeated_same_night_rows": any(len(values) > 1 for values in by_night.values()),
        "maximum_delta_rv_kms": str(maximum_delta),
        "maximum_formal_sigma": str(maximum_formal_sigma),
        "maximum_floor_sigma": str(maximum_floor_sigma),
        "joint_delta20_sigma5_formal": joint20_formal,
        "joint_delta20_sigma5_floor": joint20_floor,
        "joint_delta50_sigma5_floor": joint50_floor,
        "joint_delta100_sigma5_floor": joint100_floor,
    }


def analyze_form_rows(
    *,
    overlap_path: Path,
    form_rows_path: Path,
    exact_output_path: Path,
    source_metrics_path: Path,
    summary_path: Path,
    systematic_floor_kms: Decimal = Decimal("5"),
) -> dict[str, object]:
    if systematic_floor_kms < 0 or not systematic_floor_kms.is_finite():
        raise ValueError("systematic_floor_kms must be finite and non-negative")
    expected = load_verified_overlap(overlap_path)
    if not form_rows_path.exists() or form_rows_path.stat().st_size == 0:
        raise FormRvError("LAMOST form output is missing or empty")
    exact_output_path.parent.mkdir(parents=True, exist_ok=True)
    source_metrics_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    exact_fields = [
        "obsid",
        "hou_compact_dr2_source_id",
        "hou_compact_dr3_source_id",
        "hou_compact_independent_night",
        "rv",
        "rv_err",
        "fibermask",
        "snrg",
        "snri",
        "class",
        "subclass",
        "gaia_source_id_audit_only",
    ]
    grouped: dict[str, list[RVMeasurement]] = defaultdict(list)
    seen: set[str] = set()
    matched_sources: set[str] = set()
    counts = {
        "form_rows": 0,
        "primary_quality_rows": 0,
        "missing_or_invalid_fibermask_rows": 0,
        "nonzero_fibermask_rows": 0,
        "invalid_or_missing_rv_rows": 0,
        "missing_both_snrg_snri_rows": 0,
        "snr_at_least_5_rows": 0,
        "snr_at_least_10_rows": 0,
        "snr_at_least_20_rows": 0,
        "class_star_rows": 0,
        "class_nonstar_rows": 0,
        "class_missing_rows": 0,
    }

    with form_rows_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        mapping = _headers(reader.fieldnames)
        obsid_column = _resolve(mapping, _OBSID_ALIASES, "form obsid")
        rv_column = _resolve(mapping, _RV_ALIASES, "RV")
        rv_err_column = _resolve(mapping, _RV_ERR_ALIASES, "RV error")
        fibermask_column = _resolve(mapping, ("fibermask",), "fibermask")
        with exact_output_path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(
                target, fieldnames=exact_fields, extrasaction="raise"
            )
            writer.writeheader()
            for row in reader:
                counts["form_rows"] += 1
                if None in row:
                    raise FormRvError("LAMOST form row has extra fields")
                obsid = _exact(row.get(obsid_column), _EXACT_OBSID, label="form obsid")
                if obsid in seen:
                    raise FormRvError("LAMOST form output repeats an obsid")
                seen.add(obsid)
                identity = expected.get(obsid)
                if identity is None:
                    raise FormRvError("LAMOST form returned an obsid outside the target set")
                matched_sources.add(identity.dr3_source_id)

                snrg = _optional_decimal(row.get(mapping.get("snrg", "")))
                snri = _optional_decimal(row.get(mapping.get("snri", "")))
                available_snr = [value for value in (snrg, snri) if value is not None]
                if not available_snr:
                    counts["missing_both_snrg_snri_rows"] += 1
                else:
                    best_snr = max(available_snr)
                    counts["snr_at_least_5_rows"] += int(best_snr >= Decimal("5"))
                    counts["snr_at_least_10_rows"] += int(best_snr >= Decimal("10"))
                    counts["snr_at_least_20_rows"] += int(best_snr >= Decimal("20"))

                spectral_class = str(row.get(mapping.get("class", ""), "")).strip()
                if not spectral_class:
                    counts["class_missing_rows"] += 1
                elif spectral_class.upper() == "STAR":
                    counts["class_star_rows"] += 1
                else:
                    counts["class_nonstar_rows"] += 1

                try:
                    fibermask = _integral_decimal(
                        row.get(fibermask_column), label="fibermask"
                    )
                except FormRvError:
                    counts["missing_or_invalid_fibermask_rows"] += 1
                    continue
                if fibermask != 0:
                    counts["nonzero_fibermask_rows"] += 1
                    continue

                try:
                    rv = _decimal(row.get(rv_column), label="rv")
                    rv_err = _decimal(row.get(rv_err_column), label="rv_err")
                except FormRvError:
                    counts["invalid_or_missing_rv_rows"] += 1
                    continue
                if rv_err <= 0 or rv_err > Decimal("1000") or abs(rv) > Decimal("5000"):
                    counts["invalid_or_missing_rv_rows"] += 1
                    continue

                measurement = RVMeasurement(
                    obsid=obsid,
                    source_id=identity.dr3_source_id,
                    night=identity.independent_night,
                    rv=rv,
                    rv_err=rv_err,
                )
                grouped[identity.dr3_source_id].append(measurement)
                writer.writerow(
                    {
                        "obsid": obsid,
                        "hou_compact_dr2_source_id": identity.dr2_source_id,
                        "hou_compact_dr3_source_id": identity.dr3_source_id,
                        "hou_compact_independent_night": identity.independent_night,
                        "rv": str(rv),
                        "rv_err": str(rv_err),
                        "fibermask": str(fibermask),
                        "snrg": "" if snrg is None else str(snrg),
                        "snri": "" if snri is None else str(snri),
                        "class": spectral_class,
                        "subclass": str(row.get(mapping.get("subclass", ""), "")),
                        "gaia_source_id_audit_only": str(
                            row.get(mapping.get("gaia_source_id", ""), "")
                        ),
                    }
                )
                counts["primary_quality_rows"] += 1

    source_fields = [
        "dr3_source_id",
        "valid_rv_rows",
        "distinct_rv_nights",
        "repeated_same_night_rows",
        "maximum_delta_rv_kms",
        "maximum_formal_sigma",
        "maximum_floor_sigma",
        "joint_delta20_sigma5_formal",
        "joint_delta20_sigma5_floor",
        "joint_delta50_sigma5_floor",
        "joint_delta100_sigma5_floor",
    ]
    source_rows: list[dict[str, object]] = []
    for source_id, measurements in sorted(grouped.items()):
        source_rows.append(
            {
                "dr3_source_id": source_id,
                **_source_metrics(
                    measurements, systematic_floor_kms=systematic_floor_kms
                ),
            }
        )
    with source_metrics_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=source_fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(source_rows)

    def count(predicate) -> int:
        return sum(1 for row in source_rows if predicate(row))

    summary = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "expected_obsid_count": len(expected),
        "returned_unique_obsids": len(seen),
        "missing_expected_obsids": len(expected) - len(seen),
        "matched_source_count": len(matched_sources),
        **counts,
        "sources_with_valid_rv": len(source_rows),
        "sources_with_at_least_2_rv_nights": count(
            lambda row: int(row["distinct_rv_nights"]) >= 2
        ),
        "sources_with_at_least_3_rv_nights": count(
            lambda row: int(row["distinct_rv_nights"]) >= 3
        ),
        "sources_delta_rv_at_least_20_kms": count(
            lambda row: Decimal(str(row["maximum_delta_rv_kms"])) >= Decimal("20")
        ),
        "sources_delta_rv_at_least_50_kms": count(
            lambda row: Decimal(str(row["maximum_delta_rv_kms"])) >= Decimal("50")
        ),
        "sources_delta_rv_at_least_100_kms": count(
            lambda row: Decimal(str(row["maximum_delta_rv_kms"])) >= Decimal("100")
        ),
        "sources_joint_same_pair_delta20_sigma5_formal": count(
            lambda row: bool(row["joint_delta20_sigma5_formal"])
        ),
        "sources_joint_same_pair_delta20_sigma5_floor": count(
            lambda row: bool(row["joint_delta20_sigma5_floor"])
        ),
        "sources_joint_same_pair_delta50_sigma5_floor": count(
            lambda row: bool(row["joint_delta50_sigma5_floor"])
        ),
        "sources_joint_same_pair_delta100_sigma5_floor": count(
            lambda row: bool(row["joint_delta100_sigma5_floor"])
        ),
        "maximum_valid_rv_rows_for_one_source": max(
            (int(row["valid_rv_rows"]) for row in source_rows), default=0
        ),
        "maximum_valid_rv_nights_for_one_source": max(
            (int(row["distinct_rv_nights"]) for row in source_rows), default=0
        ),
        "identity_contract": (
            "Exact verified-overlap obsid join only; form gaia_source_id is audit-only."
        ),
        "quality_contract": {
            "fibermask_required": True,
            "fibermask_required_value": 0,
            "snr_threshold_applied": False,
            "spectral_class_threshold_applied": False,
        },
        "pairwise_contract": {
            "joint_threshold_requires_same_pair": True,
            "night_reducer": (
                "best_formal_measurement_with_half_range_error_inflation"
            ),
            "systematic_floor_kms_per_epoch": str(systematic_floor_kms),
            "conservative_primary_gate": (
                "same pair delta>=20 km/s and floor-adjusted significance>=5"
            ),
        },
        "claim_boundary": (
            "Aggregate primary-quality RV variability triage only. A promoted source "
            "is not a compact object without orbital, stellar, luminous-companion, "
            "contamination, and independent follow-up validation."
        ),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("overlap", type=Path)
    parser.add_argument("form_rows", type=Path)
    parser.add_argument("--exact-output", type=Path, required=True)
    parser.add_argument("--source-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--systematic-floor-kms", type=Decimal, default=Decimal("5"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = analyze_form_rows(
        overlap_path=args.overlap,
        form_rows_path=args.form_rows,
        exact_output_path=args.exact_output,
        source_metrics_path=args.source_output,
        summary_path=args.summary_output,
        systematic_floor_kms=args.systematic_floor_kms,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
