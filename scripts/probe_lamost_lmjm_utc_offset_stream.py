#!/usr/bin/env python3
"""Stream a bounded public MEC prefix and measure aggregate LMJM-to-UTC offset."""

from __future__ import annotations

import argparse
import csv
import gzip
import http.cookiejar
import io
import json
import re
import statistics
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import probe_lamost_lmjm_utc_offset as base

_EXACT = re.compile(r"^[0-9]+$")
_DECIMAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


class StreamOffsetError(RuntimeError):
    pass


def collect_from_url(*, url: str, sample_size: int, timeout: float) -> list[tuple[str, Decimal]]:
    if not url.startswith("https://www.lamost.org/"):
        raise StreamOffsetError("catalogue URL is outside first-party HTTPS origin")
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    request = Request(
        url,
        headers={
            "User-Agent": "HOU-COMPACT/1.4 public bounded LMJM offset contract",
            "Accept": "application/gzip,application/octet-stream,*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )
    selected: list[tuple[str, Decimal]] = []
    seen: set[str] = set()
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            if status != 200:
                raise StreamOffsetError("catalogue endpoint did not return HTTP 200")
            with gzip.GzipFile(fileobj=response, mode="rb") as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8-sig", newline="") as text:
                    reader = csv.DictReader(text, delimiter="|", strict=True)
                    headers = {
                        str(name).strip().lower(): name
                        for name in (reader.fieldnames or [])
                        if str(name).strip()
                    }
                    if any(name not in headers for name in ("obs_number", "obsid_list", "midmjm_list")):
                        raise StreamOffsetError("catalogue header contract is missing")
                    for row in reader:
                        if None in row:
                            continue
                        count = str(row.get(headers["obs_number"], ""))
                        obsids = str(row.get(headers["obsid_list"], "")).split(",")
                        times = str(row.get(headers["midmjm_list"], "")).split(",")
                        if not _EXACT.fullmatch(count):
                            continue
                        if int(count) != len(obsids) or len(obsids) != len(times):
                            continue
                        for obsid, token in zip(obsids, times):
                            if obsid in seen or not _EXACT.fullmatch(obsid) or not _DECIMAL.fullmatch(token):
                                continue
                            try:
                                value = Decimal(token)
                            except InvalidOperation:
                                continue
                            if not value.is_finite() or value < 0:
                                continue
                            seen.add(obsid)
                            selected.append((obsid, value))
                            if len(selected) >= sample_size:
                                return selected
    except (HTTPError, URLError, TimeoutError, OSError, gzip.BadGzipFile, csv.Error) as error:
        raise StreamOffsetError(f"bounded catalogue stream failed: {type(error).__name__}") from error
    raise StreamOffsetError("bounded catalogue stream yielded too few pairs")


def run(*, url: str, output: Path, sample_size: int, timeout: float) -> dict[str, Any]:
    pairs = collect_from_url(url=url, sample_size=sample_size, timeout=timeout)
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    offsets: list[float] = []
    encodings: dict[str, int] = {}
    for obsid, midmjm in pairs:
        fits_mjd, encoding = base._fits_time(opener, obsid=obsid, timeout=timeout)
        offsets.append((float(midmjm / Decimal(1440)) - fits_mjd) * 86400.0)
        encodings[encoding] = encodings.get(encoding, 0) + 1

    contracts: dict[str, dict[str, Any]] = {}
    for label, applied in base._STANDARD_OFFSETS_SECONDS.items():
        signed = [value - applied for value in offsets]
        absolute = [abs(value) for value in signed]
        contracts[label] = {
            "applied_offset_seconds": applied,
            "median_signed_residual_seconds": statistics.median(signed),
            "median_absolute_residual_seconds": statistics.median(absolute),
            "maximum_absolute_residual_seconds": max(absolute),
            "within_1_second": sum(value <= 1.0 for value in absolute),
            "within_60_seconds": sum(value <= 60.0 for value in absolute),
            "within_300_seconds": sum(value <= 300.0 for value in absolute),
        }
    best = min(
        contracts,
        key=lambda name: (
            float(contracts[name]["maximum_absolute_residual_seconds"]),
            float(contracts[name]["median_absolute_residual_seconds"]),
        ),
    )
    result = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "status": "success",
        "catalogue_transport": "bounded HTTP gzip prefix; intentionally closed after sample collection",
        "sample_pairs": len(offsets),
        "fits_encoding_counts": dict(sorted(encodings.items())),
        "raw_midmjm_over_1440_minus_fits_mjd_seconds": {
            "minimum": min(offsets),
            "maximum": max(offsets),
            "median": statistics.median(offsets),
            "span": max(offsets) - min(offsets),
            "nearest_second_histogram": base._rounded_histogram(offsets, quantum=1.0),
        },
        "tested_offset_contracts": contracts,
        "best_standard_offset": best,
        "best_standard_offset_seconds": base._STANDARD_OFFSETS_SECONDS[best],
        "privacy_contract": (
            "Only aggregate offsets from official public non-candidate spectra are persisted. "
            "No source ID, obsid, row, coordinate, RV, timestamp, query string, or FITS bytes are written."
        ),
        "claim_boundary": "Universal time-coordinate contract only; no HOU-COMPACT candidate is inspected.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://www.lamost.org/dr8/v1.0/catdl?name=dr8_v1.0_LRS_mec.csv.gz",
    )
    parser.add_argument("--output", type=Path, default=Path("lamost_lmjm_utc_offset_contract.json"))
    parser.add_argument("--sample-size", type=int, default=9)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    try:
        result = run(
            url=args.url,
            output=args.output,
            sample_size=args.sample_size,
            timeout=args.timeout,
        )
    except Exception as error:
        result = {
            "schema_version": "0.2",
            "candidate_safe": True,
            "status": "failure",
            "error_type": type(error).__name__,
            "safe_error": str(error)[:500],
            "privacy_contract": "No source-level value is emitted on failure.",
        }
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
