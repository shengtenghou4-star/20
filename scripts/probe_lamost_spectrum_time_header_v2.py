#!/usr/bin/env python3
"""Candidate-safe v2 single-spectrum timing probe with gzip FITS support.

LAMOST commonly distributes low-resolution spectra as ``.fits.gz``. This thin layer
reuses the audited public-sample discovery and FITS-header inspection from v1, but
accepts either a raw FITS stream or a bounded gzip stream whose CRC is verified by
reading to EOF. It also records safe transport diagnostics when no FITS payload is
available and treats the spectrum-info endpoint as optional.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.cookiejar
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

import probe_lamost_spectrum_time_header as base

_GZIP_MAGIC = b"\x1f\x8b"
_MAX_FITS_BYTES = 64 * 1024 * 1024


def _bounded_gunzip(raw: bytes, maximum_bytes: int = _MAX_FITS_BYTES) -> bytes:
    if maximum_bytes < 1:
        raise ValueError("maximum_bytes must be positive")
    output = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as compressed:
            while True:
                chunk = compressed.read(min(1024 * 1024, maximum_bytes + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > maximum_bytes:
                    raise base.SpectrumTimeContractError(
                        "fits_decompressed_too_large",
                        "gzip FITS exceeded the bounded decompressed-size contract",
                    )
    except (gzip.BadGzipFile, EOFError, OSError) as error:
        raise base.SpectrumTimeContractError(
            "fits_gzip_invalid",
            f"gzip FITS integrity check failed: {type(error).__name__}",
        ) from error
    return bytes(output)


def _decode_fits_payload(raw: bytes) -> tuple[bytes | None, dict[str, Any]]:
    transport = {
        "raw_fits_magic": raw.startswith(base._FITS_MAGIC),
        "gzip_magic": raw.startswith(_GZIP_MAGIC),
        "wire_bytes": len(raw),
        "wire_sha256": hashlib.sha256(raw).hexdigest(),
    }
    if raw.startswith(base._FITS_MAGIC):
        transport.update(
            {
                "encoding": "identity",
                "decoded_fits_magic": True,
                "decoded_bytes": len(raw),
                "decoded_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        return raw, transport
    if not raw.startswith(_GZIP_MAGIC):
        transport.update(
            {
                "encoding": "unknown",
                "decoded_fits_magic": False,
            }
        )
        return None, transport
    decoded = _bounded_gunzip(raw)
    is_fits = decoded.startswith(base._FITS_MAGIC)
    transport.update(
        {
            "encoding": "gzip",
            "decoded_fits_magic": is_fits,
            "decoded_bytes": len(decoded),
            "decoded_sha256": hashlib.sha256(decoded).hexdigest(),
            "gzip_crc_read_to_eof": True,
        }
    )
    return (decoded if is_fits else None), transport


def _fetch_fits_v2(
    opener: Any,
    *,
    obsid: str,
    info_payload: Any,
    timeout: float,
) -> tuple[bytes | None, dict[str, Any]]:
    base_url = "https://www.lamost.org/openapi/dr8/v1.0/lrs/spectrum/fits"
    candidates = [f"{base_url}?{urlencode({'obsid': obsid})}"]
    candidates.extend(base._same_origin_followup_urls(info_payload, base_url=base_url))
    attempts: list[dict[str, Any]] = []
    index = 0
    while index < len(candidates) and index < 20:
        candidate = candidates[index]
        index += 1
        request = Request(
            candidate,
            headers={
                "User-Agent": "HOU-COMPACT/1.3 public gzip spectrum-time contract",
                "Accept": (
                    "application/fits,application/gzip,application/octet-stream,*/*;q=0.1"
                ),
                "Accept-Encoding": "identity",
            },
        )
        try:
            status, final_url, content_type, disposition, raw = base._open_bounded(
                opener,
                request,
                timeout=timeout,
                maximum_bytes=_MAX_FITS_BYTES,
            )
        except base.SpectrumTimeContractError as error:
            attempts.append(
                {
                    "status": "failure",
                    "error_code": error.code,
                    "requested_path": base._safe_path(candidate),
                }
            )
            continue

        fits_raw, decode = _decode_fits_payload(raw)
        attempts.append(
            {
                "status": "success" if fits_raw is not None else "non_fits",
                "http_status": status,
                "requested_path": base._safe_path(candidate),
                "final_url_path": base._safe_path(final_url),
                "content_type": content_type,
                "content_disposition_present": bool(disposition.strip()),
                "decode_contract": decode,
            }
        )
        if fits_raw is not None:
            return fits_raw, {
                "attempts": attempts,
                "successful_attempt_index": len(attempts) - 1,
            }

        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for followup in base._same_origin_followup_urls(payload, base_url=final_url):
            if followup not in candidates and len(candidates) < 20:
                candidates.append(followup)

    return None, {
        "attempts": attempts,
        "successful_attempt_index": None,
        "candidate_url_count": len(candidates),
    }


def probe(*, output: Path, timeout: float = 180.0) -> dict[str, Any]:
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    _, obsid, discovery = base._fetch_sample_and_obsid(opener, timeout=timeout)

    try:
        info_contract, info_payload = base._fetch_info(
            opener,
            obsid=obsid,
            timeout=timeout,
        )
        info_contract = {"status": "success", **info_contract}
    except base.SpectrumTimeContractError as error:
        info_contract = {
            "status": "failure",
            "error_code": error.code,
            "safe_error": str(error),
        }
        info_payload = {}

    fits_raw, fits_transport = _fetch_fits_v2(
        opener,
        obsid=obsid,
        info_payload=info_payload,
        timeout=timeout,
    )
    if fits_raw is None:
        result = {
            "schema_version": "0.2",
            "candidate_safe": True,
            "status": "failure",
            "error_code": "fits_unavailable",
            "discovery_contract": discovery,
            "spectrum_info_contract": info_contract,
            "fits_transport_contract": fits_transport,
            "privacy_contract": (
                "No sample Gaia ID, obsid, filename, coordinate, RV, URL query, timestamp "
                "value, or response row is persisted."
            ),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        return result

    header_contract = base._inspect_fits_header(fits_raw, expected_obsid=obsid)
    status = (
        "success"
        if header_contract["precise_observation_midpoint_available"]
        else "failure"
    )
    result = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "status": status,
        "discovery_contract": discovery,
        "spectrum_info_contract": info_contract,
        "fits_transport_contract": fits_transport,
        "fits_header_contract": header_contract,
        "replacement_assessment": {
            "single_spectrum_header_can_supply_exact_obsid_time": bool(
                header_contract["precise_observation_midpoint_available"]
            ),
            "required_private_cross_check": (
                "FITS DATE-OBS must agree with every MEC-matched candidate obsid within "
                "the documented timing semantics before filling MEC-missing times"
            ),
        },
        "privacy_contract": (
            "No sample Gaia ID, obsid, filename, coordinate, RV, URL query, timestamp value, "
            "or FITS payload is persisted. Only safe shapes, hashes, paths, encoding metadata, "
            "and exact-identity booleans are retained."
        ),
        "claim_boundary": (
            "A public FITS-header timing contract only enables a private exact-time bridge. "
            "It does not validate an RV, orbit, companion, or compact-object candidate."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("lamost_spectrum_time_header_contract.json"),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    try:
        result = probe(output=args.output, timeout=args.timeout)
    except Exception as error:
        result = base._write_failure(args.output, error)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
