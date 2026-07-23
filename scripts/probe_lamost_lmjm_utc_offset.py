#!/usr/bin/env python3
"""Fingerprint the LMJM-to-UTC conversion using public non-candidate spectra.

The probe reads a bounded number of rows from the official LAMOST DR8 LRS
multiple-epoch catalogue, downloads the corresponding first-party gzip FITS files,
and compares raw ``midmjm / 1440`` with FITS ``DATE-OBS`` converted to UTC MJD.

Only aggregate offset/residual statistics are persisted. Source identifiers, obsids,
coordinates, RVs, timestamps, catalogue rows, URLs with query strings, and FITS bytes
are never written to output or logs.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import http.cookiejar
import io
import json
import math
import re
import statistics
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.request import HTTPCookieProcessor, build_opener

from astropy.io import fits
from astropy.time import Time

import probe_lamost_spectrum_time_header_v2 as fits_probe

_EXACT_OBSID = re.compile(r"^[0-9]+$")
_ORDINARY_DECIMAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_STANDARD_OFFSETS_SECONDS = {
    "zero": 0.0,
    "utc_plus_8_hours": 8.0 * 3600.0,
    "lamost_lmjd_5_over_6_day": 20.0 * 3600.0,
    "one_day": 24.0 * 3600.0,
}


class OffsetProbeError(RuntimeError):
    """Candidate-safe error with no source-level value in its message."""



def _safe_decimal(token: object, *, label: str) -> Decimal:
    text = "" if token is None else str(token)
    if text != text.strip() or not _ORDINARY_DECIMAL.fullmatch(text):
        raise OffsetProbeError(f"{label} violates ordinary-decimal contract")
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise OffsetProbeError(f"{label} is not decimal") from error
    if not value.is_finite() or value < 0:
        raise OffsetProbeError(f"{label} is outside supported range")
    return value



def _collect_public_pairs(catalogue: Path, *, sample_size: int) -> list[tuple[str, Decimal]]:
    if sample_size < 3 or sample_size > 30:
        raise ValueError("sample_size must be in [3, 30]")
    if not catalogue.exists() or catalogue.stat().st_size == 0:
        raise OffsetProbeError("catalogue is missing or empty")
    selected: list[tuple[str, Decimal]] = []
    seen: set[str] = set()
    try:
        with gzip.open(catalogue, mode="rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="|", strict=True)
            headers = {
                str(name).strip().lower(): name
                for name in (reader.fieldnames or [])
                if str(name).strip()
            }
            required = ("obs_number", "obsid_list", "midmjm_list")
            if any(name not in headers for name in required):
                raise OffsetProbeError("catalogue header contract is missing")
            for row in reader:
                if None in row:
                    continue
                obsids_raw = str(row.get(headers["obsid_list"], ""))
                midmjms_raw = str(row.get(headers["midmjm_list"], ""))
                count_raw = str(row.get(headers["obs_number"], ""))
                if not _EXACT_OBSID.fullmatch(count_raw):
                    continue
                obsids = obsids_raw.split(",")
                midmjms = midmjms_raw.split(",")
                if int(count_raw) != len(obsids) or len(obsids) != len(midmjms):
                    continue
                for obsid, midmjm in zip(obsids, midmjms):
                    if obsid in seen or not _EXACT_OBSID.fullmatch(obsid):
                        continue
                    try:
                        minute = _safe_decimal(midmjm, label="midmjm")
                    except OffsetProbeError:
                        continue
                    seen.add(obsid)
                    selected.append((obsid, minute))
                    if len(selected) >= sample_size:
                        return selected
    except (gzip.BadGzipFile, EOFError, OSError, csv.Error) as error:
        raise OffsetProbeError(
            f"catalogue stream failed: {type(error).__name__}"
        ) from error
    raise OffsetProbeError("catalogue did not yield enough valid public pairs")



def _fits_time(opener: Any, *, obsid: str, timeout: float) -> tuple[float, str]:
    raw, transport = fits_probe._fetch_fits_v2(
        opener,
        obsid=obsid,
        info_payload={},
        timeout=timeout,
    )
    if raw is None:
        raise OffsetProbeError("first-party FITS was unavailable")
    attempts = transport.get("attempts", [])
    successful = transport.get("successful_attempt_index")
    if not isinstance(successful, int) or not (0 <= successful < len(attempts)):
        raise OffsetProbeError("FITS transport success receipt is invalid")
    encoding = str(attempts[successful].get("decode_contract", {}).get("encoding", ""))
    try:
        with fits.open(
            io.BytesIO(raw),
            mode="readonly",
            memmap=False,
            do_not_scale_image_data=True,
            ignore_missing_end=False,
        ) as hdul:
            header = hdul[0].header
            header_obsid = str(header.get("OBSID", "")).strip()
            if header_obsid != obsid:
                raise OffsetProbeError("FITS header identity mismatch")
            token = str(header.get("DATE-OBS", "")).strip()
            if not token or "T" not in token:
                raise OffsetProbeError("FITS DATE-OBS lacks full timestamp")
            mjd = float(Time(token, format="isot", scale="utc").mjd)
    except OffsetProbeError:
        raise
    except Exception as error:
        raise OffsetProbeError(f"FITS header parse failed: {type(error).__name__}") from error
    if not math.isfinite(mjd):
        raise OffsetProbeError("FITS UTC MJD is non-finite")
    return mjd, encoding



def _rounded_histogram(values: list[float], *, quantum: float) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        rounded = round(value / quantum) * quantum
        key = f"{rounded:.0f}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: float(item[0])))



def probe(
    *,
    catalogue: Path,
    output: Path,
    sample_size: int = 9,
    timeout: float = 180.0,
) -> dict[str, Any]:
    pairs = _collect_public_pairs(catalogue, sample_size=sample_size)
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    raw_offsets_seconds: list[float] = []
    encodings: dict[str, int] = {}
    for obsid, midmjm in pairs:
        fits_mjd, encoding = _fits_time(opener, obsid=obsid, timeout=timeout)
        raw_mjd = float(midmjm / Decimal(1440))
        raw_offsets_seconds.append((raw_mjd - fits_mjd) * 86400.0)
        encodings[encoding] = encodings.get(encoding, 0) + 1

    offset_contracts: dict[str, dict[str, Any]] = {}
    for label, offset_seconds in _STANDARD_OFFSETS_SECONDS.items():
        residuals = [value - offset_seconds for value in raw_offsets_seconds]
        absolute = [abs(value) for value in residuals]
        offset_contracts[label] = {
            "applied_offset_seconds": offset_seconds,
            "median_signed_residual_seconds": statistics.median(residuals),
            "median_absolute_residual_seconds": statistics.median(absolute),
            "maximum_absolute_residual_seconds": max(absolute),
            "within_1_second": sum(value <= 1.0 for value in absolute),
            "within_60_seconds": sum(value <= 60.0 for value in absolute),
            "within_300_seconds": sum(value <= 300.0 for value in absolute),
        }
    best_label = min(
        offset_contracts,
        key=lambda name: (
            float(offset_contracts[name]["maximum_absolute_residual_seconds"]),
            float(offset_contracts[name]["median_absolute_residual_seconds"]),
        ),
    )
    median_offset = statistics.median(raw_offsets_seconds)
    result = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "success",
        "sample_pairs": len(raw_offsets_seconds),
        "fits_encoding_counts": dict(sorted(encodings.items())),
        "raw_midmjm_over_1440_minus_fits_mjd_seconds": {
            "minimum": min(raw_offsets_seconds),
            "maximum": max(raw_offsets_seconds),
            "median": median_offset,
            "span": max(raw_offsets_seconds) - min(raw_offsets_seconds),
            "nearest_second_histogram": _rounded_histogram(
                raw_offsets_seconds, quantum=1.0
            ),
        },
        "tested_offset_contracts": offset_contracts,
        "best_standard_offset": best_label,
        "best_standard_offset_seconds": _STANDARD_OFFSETS_SECONDS[best_label],
        "privacy_contract": (
            "Only aggregate offset/residual statistics from official public non-candidate "
            "spectra are retained. No source ID, obsid, row, coordinate, RV, timestamp, "
            "URL query, or FITS payload is persisted."
        ),
        "claim_boundary": (
            "This contract determines only the universal LMJM-to-UTC time conversion. "
            "It does not inspect or classify any HOU-COMPACT candidate."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--output", type=Path, default=Path("lamost_lmjm_utc_offset.json"))
    parser.add_argument("--sample-size", type=int, default=9)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    try:
        result = probe(
            catalogue=args.catalogue,
            output=args.output,
            sample_size=args.sample_size,
            timeout=args.timeout,
        )
    except Exception as error:
        result = {
            "schema_version": "0.1",
            "candidate_safe": True,
            "status": "failure",
            "error_type": type(error).__name__,
            "safe_error": str(error)[:500],
            "privacy_contract": "No source-level value is emitted on failure.",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
