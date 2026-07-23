#!/usr/bin/env python3
"""Extract exact candidate times from live LAMOST MEC using verified UTC+8 conversion."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

_EXACT_OBSID = re.compile(r"^[0-9]+$")
_EXACT_SOURCE = re.compile(r"^[0-9]{10,20}$")
_DECIMAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_OFFSET_MINUTES = Decimal("480")
_MINUTES_PER_DAY = Decimal("1440")


class MecTimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Expected:
    obsid: str
    dr2: str
    dr3: str


def _headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise MecTimeError("table has no header")
    result: dict[str, str] = {}
    for name in fieldnames:
        key = str(name).strip().lower().lstrip("\ufeff")
        if not key or key in result:
            raise MecTimeError("table has empty or duplicate normalized header")
        result[key] = str(name)
    return result


def _exact(value: object, pattern: re.Pattern[str], *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not pattern.fullmatch(token):
        raise MecTimeError(f"{label} is not exact integer text")
    return token


def _decimal_token(value: object, *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not _DECIMAL.fullmatch(token):
        raise MecTimeError(f"{label} is not ordinary non-negative decimal text")
    try:
        parsed = Decimal(token)
    except InvalidOperation as error:
        raise MecTimeError(f"{label} is not decimal") from error
    if not parsed.is_finite() or parsed < 0:
        raise MecTimeError(f"{label} is outside supported range")
    return token


def decimal_places(token: str) -> int:
    return len(token.partition(".")[2]) if "." in token else 0


def lmjm_to_utc_mjd(token: str) -> str:
    exact = _decimal_token(token, label="midmjm")
    value = Decimal(exact)
    if value < _OFFSET_MINUTES:
        raise MecTimeError("midmjm precedes UTC+8 offset")
    utc = (value - _OFFSET_MINUTES) / _MINUTES_PER_DAY
    return format(utc.quantize(Decimal("0.000000000001")), "f")


def quantisation_days(token: str) -> str:
    exact = _decimal_token(token, label="midmjm")
    half_ulp_minutes = Decimal("0.5") * Decimal(1).scaleb(-decimal_places(exact))
    return format(half_ulp_minutes / _MINUTES_PER_DAY, "f")


def load_expected(path: Path) -> dict[str, Expected]:
    expected: dict[str, Expected] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        for required in (
            "obsid",
            "hou_compact_dr2_source_id",
            "hou_compact_dr3_source_id",
        ):
            if required not in mapping:
                raise MecTimeError(f"expected table lacks {required}")
        for row in reader:
            if None in row:
                raise MecTimeError("expected row has extra fields")
            obsid = _exact(row[mapping["obsid"]], _EXACT_OBSID, label="obsid")
            record = Expected(
                obsid=obsid,
                dr2=_exact(
                    row[mapping["hou_compact_dr2_source_id"]],
                    _EXACT_SOURCE,
                    label="DR2 source",
                ),
                dr3=_exact(
                    row[mapping["hou_compact_dr3_source_id"]],
                    _EXACT_SOURCE,
                    label="DR3 source",
                ),
            )
            if obsid in expected:
                raise MecTimeError("expected table repeats an obsid")
            expected[obsid] = record
    if not expected:
        raise MecTimeError("expected table contains no observations")
    return expected


def extract(
    *,
    expected_path: Path,
    catalogue_gz: Path,
    output_path: Path,
    receipt_path: Path,
) -> dict[str, object]:
    expected = load_expected(expected_path)
    boundary = re.compile(
        r"(?<![0-9])(?:"
        + "|".join(
            re.escape(value)
            for value in sorted(expected, key=lambda item: (-len(item), item))
        )
        + r")(?![0-9])"
    )
    found: dict[str, tuple[str, str]] = {}
    sources: set[str] = set()
    precision: Counter[int] = Counter()
    malformed = 0
    rows_scanned = 0
    started = time.monotonic()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "obsid",
        "hou_compact_dr2_source_id",
        "hou_compact_dr3_source_id",
        "midmjm",
        "mid_mjd",
        "time_quantisation_half_width_days",
        "time_source",
    ]
    try:
        with gzip.open(catalogue_gz, "rt", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, delimiter="|", strict=True)
            mapping = _headers(reader.fieldnames)
            for required in ("obs_number", "obsid_list", "midmjm_list"):
                if required not in mapping:
                    raise MecTimeError(f"MEC table lacks {required}")
            with output_path.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=fields, extrasaction="raise")
                writer.writeheader()
                for rows_scanned, row in enumerate(reader, start=1):
                    if None in row:
                        raise MecTimeError("MEC row has extra fields")
                    raw_obsids = str(row.get(mapping["obsid_list"], ""))
                    raw_times = str(row.get(mapping["midmjm_list"], ""))
                    touches = boundary.search(raw_obsids) is not None
                    try:
                        count = int(
                            _exact(
                                row.get(mapping["obs_number"]),
                                _EXACT_OBSID,
                                label="obs_number",
                            )
                        )
                        obsids = raw_obsids.split(",")
                        tokens = raw_times.split(",")
                        if (
                            count != len(obsids)
                            or count != len(tokens)
                            or any(not _EXACT_OBSID.fullmatch(value) for value in obsids)
                        ):
                            raise MecTimeError("MEC list alignment failed")
                        tokens = [
                            _decimal_token(value, label="midmjm element")
                            for value in tokens
                        ]
                    except (MecTimeError, ValueError):
                        if touches:
                            raise
                        malformed += 1
                        continue
                    for token in tokens:
                        precision[decimal_places(token)] += 1
                    for obsid, token in zip(obsids, tokens):
                        identity = expected.get(obsid)
                        if identity is None:
                            continue
                        current = (token, identity.dr3)
                        if obsid in found:
                            raise MecTimeError("MEC table repeats an expected obsid")
                        found[obsid] = current
                        sources.add(identity.dr3)
                        writer.writerow(
                            {
                                "obsid": obsid,
                                "hou_compact_dr2_source_id": identity.dr2,
                                "hou_compact_dr3_source_id": identity.dr3,
                                "midmjm": token,
                                "mid_mjd": lmjm_to_utc_mjd(token),
                                "time_quantisation_half_width_days": quantisation_days(token),
                                "time_source": "mec_lmjm_utc_plus_8_corrected",
                            }
                        )
    except (gzip.BadGzipFile, EOFError, OSError, csv.Error) as error:
        raise MecTimeError(f"MEC gzip stream failed: {type(error).__name__}") from error

    receipt = {
        "schema_version": "1.0",
        "status": "success",
        "candidate_sensitive": True,
        "expected_obsids": len(expected),
        "scan": {
            "catalogue_rows": rows_scanned,
            "malformed_unmatched_rows": malformed,
            "matched_obsids": len(found),
            "matched_sources": len(sources),
            "expected_obsids_without_multi_epoch_time": len(expected) - len(found),
            "midmjm_decimal_place_histogram": {
                str(key): precision[key] for key in sorted(precision)
            },
        },
        "time_contract": {
            "table_delimiter": "|",
            "list_separator": ",",
            "input_coordinate": "LAMOST local modified-Julian minutes (UTC+8)",
            "utc_mjd_conversion": "(Decimal(midmjm) - 480) / 1440",
            "quantisation_rule": "half unit in last written LMJM decimal place",
            "public_verification": (
                "nine first-party non-candidate MEC/FITS pairs; 9/9 within 60 seconds "
                "after subtracting UTC+8, with 0/30-second quantisation structure"
            ),
        },
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path)
    parser.add_argument("catalogue_gz", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = extract(
        expected_path=args.expected,
        catalogue_gz=args.catalogue_gz,
        output_path=args.output,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
