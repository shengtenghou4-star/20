#!/usr/bin/env python3
"""Cross-validate UTC-corrected MEC times with exact FITS DATE-OBS and fill 12/12."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from astropy.io import fits
from astropy.time import Time

_EXACT_OBSID = re.compile(r"^[0-9]+$")
_EXACT_SOURCE = re.compile(r"^[0-9]{10,20}$")
_DATE_OBS = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T"
    r"(?P<hour>[0-2]\d):(?P<minute>[0-5]\d):(?P<second>[0-5]\d)"
    r"(?:\.(?P<fraction>\d+))?$"
)


class HybridTimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Identity:
    obsid: str
    dr2: str
    dr3: str


@dataclass(frozen=True)
class TimePoint:
    obsid: str
    source: str
    mjd: float
    error_days: float


def _headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise HybridTimeError("table has no header")
    result: dict[str, str] = {}
    for name in fieldnames:
        key = str(name).strip().lower().lstrip("\ufeff")
        if not key or key in result:
            raise HybridTimeError("table has empty or duplicate normalized header")
        result[key] = str(name)
    return result


def _exact(value: object, pattern: re.Pattern[str], *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not pattern.fullmatch(token):
        raise HybridTimeError(f"{label} is not exact integer text")
    return token


def _finite(value: object, *, label: str, allow_zero: bool = False) -> float:
    token = "" if value is None else str(value)
    if token != token.strip() or not token:
        raise HybridTimeError(f"{label} is missing or contains whitespace")
    try:
        result = float(token)
    except ValueError as error:
        raise HybridTimeError(f"{label} is not numeric") from error
    if not math.isfinite(result):
        raise HybridTimeError(f"{label} is not finite")
    if (allow_zero and result < 0) or (not allow_zero and result <= 0):
        raise HybridTimeError(f"{label} is outside supported range")
    return result


def load_expected(path: Path) -> dict[str, Identity]:
    result: dict[str, Identity] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        required = (
            "obsid",
            "hou_compact_dr2_source_id",
            "hou_compact_dr3_source_id",
        )
        if any(name not in mapping for name in required):
            raise HybridTimeError("expected table lacks identity columns")
        for row in reader:
            obsid = _exact(row[mapping["obsid"]], _EXACT_OBSID, label="obsid")
            if obsid in result:
                raise HybridTimeError("expected table repeats obsid")
            result[obsid] = Identity(
                obsid,
                _exact(
                    row[mapping["hou_compact_dr2_source_id"]],
                    _EXACT_SOURCE,
                    label="DR2 source",
                ),
                _exact(
                    row[mapping["hou_compact_dr3_source_id"]],
                    _EXACT_SOURCE,
                    label="DR3 source",
                ),
            )
    if not result:
        raise HybridTimeError("expected table is empty")
    return result


def load_mec(path: Path, expected: dict[str, Identity]) -> dict[str, TimePoint]:
    result: dict[str, TimePoint] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        for required in (
            "obsid",
            "hou_compact_dr3_source_id",
            "mid_mjd",
            "time_quantisation_half_width_days",
        ):
            if required not in mapping:
                raise HybridTimeError(f"MEC times lack {required}")
        for row in reader:
            obsid = _exact(row[mapping["obsid"]], _EXACT_OBSID, label="MEC obsid")
            identity = expected.get(obsid)
            if identity is None:
                raise HybridTimeError("MEC time contains obsid outside expected set")
            source = _exact(
                row[mapping["hou_compact_dr3_source_id"]],
                _EXACT_SOURCE,
                label="MEC source",
            )
            if source != identity.dr3:
                raise HybridTimeError("MEC source identity mismatch")
            if obsid in result:
                raise HybridTimeError("MEC time repeats obsid")
            result[obsid] = TimePoint(
                obsid,
                source,
                _finite(row[mapping["mid_mjd"]], label="MEC UTC MJD"),
                _finite(
                    row[mapping["time_quantisation_half_width_days"]],
                    label="MEC timing error",
                    allow_zero=True,
                ),
            )
    return result


def parse_date_obs(value: object) -> tuple[float, float, int]:
    token = "" if value is None else str(value)
    if token != token.strip() or not token:
        raise HybridTimeError("DATE-OBS is missing or unsafe")
    match = _DATE_OBS.fullmatch(token)
    if match is None:
        raise HybridTimeError("DATE-OBS is not ordinary ISO UTC")
    fraction = match.group("fraction") or ""
    digits = len(fraction)
    error_days = 0.5 * 10.0 ** (-digits) / 86400.0
    try:
        mjd = float(Time(token, format="isot", scale="utc").mjd)
    except Exception as error:
        raise HybridTimeError(
            f"DATE-OBS UTC parse failed: {type(error).__name__}"
        ) from error
    return mjd, error_days, digits


def load_fits_times(
    manifest: Path,
    expected: dict[str, Identity],
) -> tuple[dict[str, tuple[float, float, int]], dict[str, Path]]:
    paths: dict[str, Path] = {}
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        if "obsid" not in mapping or "fits_path" not in mapping:
            raise HybridTimeError("FITS manifest lacks columns")
        for row in reader:
            obsid = _exact(row[mapping["obsid"]], _EXACT_OBSID, label="manifest obsid")
            if obsid not in expected or obsid in paths:
                raise HybridTimeError("FITS manifest identity contract failed")
            path = Path(str(row[mapping["fits_path"]]))
            if not path.exists() or path.stat().st_size == 0:
                raise HybridTimeError("FITS file is missing")
            paths[obsid] = path
    if set(paths) != set(expected):
        raise HybridTimeError("FITS manifest does not cover every expected obsid")
    times: dict[str, tuple[float, float, int]] = {}
    for obsid, path in sorted(paths.items()):
        try:
            with fits.open(
                path,
                mode="readonly",
                memmap=False,
                do_not_scale_image_data=True,
                ignore_missing_end=False,
            ) as hdul:
                header_obsid = _exact(
                    hdul[0].header.get("OBSID"), _EXACT_OBSID, label="FITS OBSID"
                )
                if header_obsid != obsid:
                    raise HybridTimeError("FITS OBSID mismatch")
                times[obsid] = parse_date_obs(hdul[0].header.get("DATE-OBS"))
        except HybridTimeError:
            raise
        except Exception as error:
            raise HybridTimeError(
                f"FITS header read failed: {type(error).__name__}"
            ) from error
    return times, paths


def build(
    *,
    expected_path: Path,
    mec_path: Path,
    fits_manifest: Path,
    output_path: Path,
    private_receipt_path: Path,
    safe_summary_path: Path,
) -> dict[str, object]:
    expected = load_expected(expected_path)
    mec = load_mec(mec_path, expected)
    fits_times, _ = load_fits_times(fits_manifest, expected)
    mismatches = 0
    maximum_residual = 0.0
    crosschecks: list[dict[str, object]] = []
    for obsid, mec_point in sorted(mec.items()):
        fits_mjd, fits_error, _ = fits_times[obsid]
        residual = abs(mec_point.mjd - fits_mjd)
        allowed = mec_point.error_days + fits_error + 1e-12
        maximum_residual = max(maximum_residual, residual * 86400.0)
        agrees = residual <= allowed
        mismatches += int(not agrees)
        crosschecks.append(
            {
                "obsid": obsid,
                "source_id": mec_point.source,
                "mec_mjd": mec_point.mjd,
                "fits_mjd": fits_mjd,
                "residual_seconds": residual * 86400.0,
                "allowed_seconds": allowed * 86400.0,
                "agrees": agrees,
            }
        )
    if mismatches:
        raise HybridTimeError("UTC-corrected MEC and FITS times disagree")

    fields = [
        "obsid",
        "hou_compact_dr2_source_id",
        "hou_compact_dr3_source_id",
        "mid_mjd",
        "time_quantisation_half_width_days",
        "time_source",
        "mec_crosschecked_with_fits",
    ]
    sources: set[str] = set()
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        for obsid, identity in sorted(expected.items()):
            fits_mjd, fits_error, _ = fits_times[obsid]
            mec_point = mec.get(obsid)
            if mec_point is not None:
                mjd = mec_point.mjd
                error = mec_point.error_days
                source = "mec_utc_crosschecked_fits"
                crosschecked = True
            else:
                mjd = fits_mjd
                error = fits_error
                source = "fits_date_obs_mec_missing"
                crosschecked = False
            sources.add(identity.dr3)
            writer.writerow(
                {
                    "obsid": obsid,
                    "hou_compact_dr2_source_id": identity.dr2,
                    "hou_compact_dr3_source_id": identity.dr3,
                    "mid_mjd": format(mjd, ".12f"),
                    "time_quantisation_half_width_days": format(error, ".16g"),
                    "time_source": source,
                    "mec_crosschecked_with_fits": crosschecked,
                }
            )
    digit_hist = Counter(value[2] for value in fits_times.values())
    private = {
        "schema_version": "1.0",
        "candidate_sensitive": True,
        "status": "success",
        "expected_obsids": len(expected),
        "mec_obsids": len(mec),
        "fits_obsids": len(fits_times),
        "crosschecks": crosschecks,
        "mec_missing_filled_by_fits": len(expected) - len(mec),
        "final_obsids": len(expected),
        "final_sources": len(sources),
    }
    private_receipt_path.write_text(
        json.dumps(private, indent=2, sort_keys=True), encoding="utf-8"
    )
    safe = {
        "schema_version": "1.0",
        "candidate_safe": True,
        "expected_obsids": len(expected),
        "mec_obsids": len(mec),
        "fits_obsids": len(fits_times),
        "mec_fits_crosschecks": len(crosschecks),
        "mec_fits_crosscheck_mismatches": mismatches,
        "mec_missing_obsids_filled_by_fits": len(expected) - len(mec),
        "final_obsids": len(expected),
        "final_sources": len(sources),
        "fits_date_obs_fractional_second_digits": {
            str(key): digit_hist[key] for key in sorted(digit_hist)
        },
        "maximum_crosscheck_residual_seconds": maximum_residual,
        "contract": {
            "mec_coordinate": "UTC MJD after verified subtraction of 480 LMJM minutes",
            "crosscheck": "absolute residual <= explicit MEC plus FITS half-ULP",
            "selection": "crosschecked MEC preferred; FITS fills MEC-missing obsids",
        },
        "claim_boundary": "Exact hybrid timing only; no companion classification.",
    }
    safe_summary_path.write_text(
        json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8"
    )
    return safe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path)
    parser.add_argument("mec_times", type=Path)
    parser.add_argument("fits_manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--private-receipt", type=Path, required=True)
    parser.add_argument("--safe-summary", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        expected_path=args.expected,
        mec_path=args.mec_times,
        fits_manifest=args.fits_manifest,
        output_path=args.output,
        private_receipt_path=args.private_receipt,
        safe_summary_path=args.safe_summary,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
