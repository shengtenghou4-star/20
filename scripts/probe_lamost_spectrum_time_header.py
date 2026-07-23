#!/usr/bin/env python3
"""Probe first-party LAMOST single-spectrum timing without persisting row values.

The probe obtains one spectrum through LAMOST's own public Gaia DR2 sample, verifies
exact obsid identity, inspects the OpenAPI spectrum-info response, and downloads the
corresponding public FITS file. Only response hashes, generic key names, value shapes,
and FITS header keyword shapes are retained. The sample Gaia ID, obsid, coordinates,
velocities, filenames, URLs with query strings, and timestamp values are never written.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import io
import json
import math
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from astropy.io import fits

from hou_compact.lamost_form_rv import _bounded_read, _multipart_body, _parse_delimited
from hou_compact.lamost_form_rv_v2 import normalize_parsed_table

_EXACT_SOURCE = re.compile(r"^[0-9]{10,20}$")
_EXACT_OBSID = re.compile(r"^[0-9]+$")
_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_ORDINARY_DECIMAL = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T| )[0-2]\d:[0-5]\d:"
    r"[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
_FITS_MAGIC = b"SIMPLE  ="
_TIME_KEY_TOKENS = (
    "date",
    "time",
    "mjd",
    "lmjd",
    "lmjm",
    "utc",
    "exp",
    "begin",
    "beg",
    "end",
)
_FITS_REVIEW_KEYS = (
    "OBSID",
    "DATE-OBS",
    "DATE-BEG",
    "DATE-END",
    "MJD-OBS",
    "MJD",
    "LMJD",
    "LMJMLIST",
    "BESTEXP",
    "EXPTIME",
    "NEXP",
    "NEXP_B",
    "NEXP_R",
)


class SpectrumTimeContractError(RuntimeError):
    """A candidate-safe probe error with a non-sensitive code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _safe_path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or "/"


def _open_bounded(
    opener: Any,
    request: Request,
    *,
    timeout: float,
    maximum_bytes: int,
) -> tuple[int, str, str, str, bytes]:
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            final_url = str(getattr(response, "geturl", lambda: request.full_url)())
            content_type = str(response.headers.get("Content-Type", ""))
            disposition = str(response.headers.get("Content-Disposition", ""))
            raw = _bounded_read(response, maximum_bytes)
    except HTTPError as error:
        raise SpectrumTimeContractError(
            "http_error", f"first-party endpoint returned HTTP {error.code}"
        ) from error
    except URLError as error:
        raise SpectrumTimeContractError(
            "transport_error", f"first-party endpoint transport failed: {type(error.reason).__name__}"
        ) from error
    if status != 200:
        raise SpectrumTimeContractError(
            "http_status", f"first-party endpoint returned HTTP {status}"
        )
    return status, final_url, content_type, disposition, raw


def _scalar_shape(value: Any) -> dict[str, Any]:
    """Describe a scalar without returning its value."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {
            "type": "integer",
            "decimal_digits": len(str(abs(value))),
            "nonnegative": value >= 0,
        }
    if isinstance(value, float):
        return {
            "type": "number",
            "finite": math.isfinite(value),
            "nonnegative": math.isfinite(value) and value >= 0,
        }
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value)}
    token = str(value).strip()
    ordinary_decimal = bool(_ORDINARY_DECIMAL.fullmatch(token))
    return {
        "type": "string",
        "length": len(token),
        "empty": not token,
        "exact_integer": bool(re.fullmatch(r"^[+-]?[0-9]+$", token)),
        "ordinary_decimal": ordinary_decimal,
        "decimal_places": (
            len(token.partition(".")[2]) if ordinary_decimal and "." in token else 0
        ),
        "iso_date": bool(_ISO_DATE.fullmatch(token)),
        "iso_datetime": bool(_ISO_DATETIME.fullmatch(token)),
        "contains_timezone_marker": bool(
            token.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", token)
        ),
        "url_like": token.startswith(("https://", "http://", "/")),
    }


def _safe_key_name(value: object) -> str | None:
    token = str(value)
    if _SAFE_KEY.fullmatch(token):
        return token
    return None


def _is_time_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _TIME_KEY_TOKENS)


def _json_contract(payload: Any) -> dict[str, Any]:
    """Return only generic JSON key/type and timing-field shape metadata."""
    safe_keys: set[str] = set()
    unsafe_key_count = 0
    value_type_counts: dict[str, int] = {}
    time_shapes: list[dict[str, Any]] = []
    obsid_values = 0
    obsid_exact_matches = 0

    def visit(value: Any, path: str, depth: int, expected_obsid: str | None) -> None:
        nonlocal unsafe_key_count, obsid_values, obsid_exact_matches
        if depth > 8:
            value_type_counts["depth_limited"] = value_type_counts.get("depth_limited", 0) + 1
            return
        if isinstance(value, dict):
            value_type_counts["object"] = value_type_counts.get("object", 0) + 1
            for raw_key, child in value.items():
                key = _safe_key_name(raw_key)
                if key is None:
                    unsafe_key_count += 1
                    child_path = f"{path}.<unsafe-key>"
                else:
                    safe_keys.add(key)
                    child_path = f"{path}.{key}"
                    if key.lower() == "obsid":
                        obsid_values += 1
                        if expected_obsid is not None and str(child).strip() == expected_obsid:
                            obsid_exact_matches += 1
                    if _is_time_key(key) and not isinstance(child, (dict, list, tuple)):
                        time_shapes.append({"path": child_path, "shape": _scalar_shape(child)})
                visit(child, child_path, depth + 1, expected_obsid)
            return
        if isinstance(value, (list, tuple)):
            value_type_counts["array"] = value_type_counts.get("array", 0) + 1
            for child in value[:1000]:
                visit(child, f"{path}[]", depth + 1, expected_obsid)
            if len(value) > 1000:
                value_type_counts["array_items_truncated"] = value_type_counts.get(
                    "array_items_truncated", 0
                ) + (len(value) - 1000)
            return
        scalar_type = _scalar_shape(value)["type"]
        value_type_counts[str(scalar_type)] = value_type_counts.get(str(scalar_type), 0) + 1

    def build(expected_obsid: str | None) -> dict[str, Any]:
        visit(payload, "$", 0, expected_obsid)
        return {
            "root_type": type(payload).__name__,
            "safe_key_names": sorted(safe_keys),
            "safe_key_count": len(safe_keys),
            "unsafe_key_count": unsafe_key_count,
            "value_type_counts": dict(sorted(value_type_counts.items())),
            "time_field_shapes": time_shapes,
            "obsid_field_count": obsid_values,
            "obsid_exact_match_count": obsid_exact_matches,
        }

    # The caller can replace the obsid counters after comparison without exposing the value.
    return {"build": build}


def _inspect_json(raw: bytes, *, expected_obsid: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SpectrumTimeContractError(
            "info_not_json", "spectrum-info response was not valid JSON"
        ) from error
    builder = _json_contract(payload)["build"]
    return builder(expected_obsid)


def _same_origin_followup_urls(payload: Any, *, base_url: str) -> list[str]:
    base = urlparse(base_url)
    found: list[str] = []

    def visit(value: Any, depth: int) -> None:
        if depth > 8:
            return
        if isinstance(value, dict):
            for child in value.values():
                visit(child, depth + 1)
            return
        if isinstance(value, (list, tuple)):
            for child in value[:1000]:
                visit(child, depth + 1)
            return
        if not isinstance(value, str):
            return
        token = value.strip()
        if not token or not token.startswith(("https://", "http://", "/")):
            return
        candidate = urljoin(base_url, token)
        parsed = urlparse(candidate)
        if parsed.scheme != "https" or parsed.netloc != base.netloc:
            return
        if candidate not in found:
            found.append(candidate)

    visit(payload, 0)
    return found


def _fetch_sample_and_obsid(
    opener: Any,
    *,
    timeout: float,
) -> tuple[str, str, dict[str, Any]]:
    sample_url = "https://www.lamost.org/dr8/v1.0/u/gaia_source_id.txt"
    search_url = "https://www.lamost.org/dr8/v1.0/search"
    action_url = "https://www.lamost.org/dr8/v1.0/q"

    sample_request = Request(
        sample_url,
        headers={
            "User-Agent": "HOU-COMPACT/1.2 public spectrum-time contract",
            "Accept": "text/plain,*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )
    sample_status, _, sample_type, _, sample_raw = _open_bounded(
        opener,
        sample_request,
        timeout=timeout,
        maximum_bytes=65536,
    )
    tokens = [
        token
        for token in re.split(r"[\s,;]+", sample_raw.decode("utf-8-sig"))
        if token
    ]
    exact_sources = [token for token in tokens if _EXACT_SOURCE.fullmatch(token)]
    if not exact_sources:
        raise SpectrumTimeContractError(
            "sample_contract", "official sample file contained no exact Gaia DR2 ID"
        )
    sample = exact_sources[0]

    search_request = Request(
        search_url,
        headers={
            "User-Agent": "HOU-COMPACT/1.2 public spectrum-time contract",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    search_status, _, search_type, _, search_raw = _open_bounded(
        opener,
        search_request,
        timeout=timeout,
        maximum_bytes=8 * 1024 * 1024,
    )

    output_columns = ("gaia_source_id", "obsid")
    fields: list[tuple[str, str]] = [
        ("sForm", "0"),
        ("pos.type", "none"),
        ("gaiasourcearea", sample),
        ("output.collection", "minimal"),
        ("output.fmt", "csv"),
    ]
    fields.extend((f"output.combined.{column}", "on") for column in output_columns)
    fields.append(("sBtn", "Search"))
    boundary = "----HOUCOMPACT" + secrets.token_hex(16)
    body = _multipart_body(fields, boundary)
    form_request = Request(
        action_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "HOU-COMPACT/1.2 public spectrum-time contract",
            "Accept": "text/csv,text/plain,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Origin": "https://www.lamost.org",
            "Referer": search_url,
        },
        method="POST",
    )
    form_status, form_url, form_type, form_disposition, form_raw = _open_bounded(
        opener,
        form_request,
        timeout=timeout,
        maximum_bytes=16 * 1024 * 1024,
    )
    table = normalize_parsed_table(
        _parse_delimited(form_raw, source_kind="form_post", source_url=form_url)
    )
    if table is None:
        raise SpectrumTimeContractError(
            "form_contract", "public sample form response was not a delimited table"
        )
    required = {"gaia_source_id", "obsid"}
    missing = sorted(required - set(table.columns))
    if missing:
        raise SpectrumTimeContractError(
            "form_columns", "public sample form response omitted required identity columns"
        )
    gaia_index = table.columns.index("gaia_source_id")
    obsid_index = table.columns.index("obsid")
    obsids: list[str] = []
    for row in table.rows:
        gaia_token = row[gaia_index].strip()
        obsid_token = row[obsid_index].strip()
        if gaia_token != sample:
            raise SpectrumTimeContractError(
                "form_identity", "public sample form returned a Gaia ID outside the request"
            )
        if not _EXACT_OBSID.fullmatch(obsid_token):
            raise SpectrumTimeContractError(
                "form_obsid", "public sample form returned a non-exact obsid"
            )
        if obsid_token not in obsids:
            obsids.append(obsid_token)
    if not obsids:
        raise SpectrumTimeContractError(
            "form_empty", "public sample form returned no exact spectrum obsid"
        )

    receipt = {
        "official_sample": {
            "http_status": sample_status,
            "content_type": sample_type,
            "response_bytes": len(sample_raw),
            "response_sha256": hashlib.sha256(sample_raw).hexdigest(),
            "exact_source_count": len(exact_sources),
        },
        "search_page": {
            "http_status": search_status,
            "content_type": search_type,
            "response_bytes": len(search_raw),
            "response_sha256": hashlib.sha256(search_raw).hexdigest(),
        },
        "form_response": {
            "http_status": form_status,
            "content_type": form_type,
            "content_disposition_present": bool(form_disposition.strip()),
            "final_url_path": _safe_path(form_url),
            "response_bytes": len(form_raw),
            "response_sha256": hashlib.sha256(form_raw).hexdigest(),
            "delimiter": table.delimiter,
            "row_count": len(table.rows),
            "unique_exact_obsid_count": len(obsids),
            "columns": list(table.columns),
        },
    }
    return sample, obsids[0], receipt


def _fetch_info(
    opener: Any,
    *,
    obsid: str,
    timeout: float,
) -> tuple[dict[str, Any], Any]:
    base_url = "https://www.lamost.org/openapi/dr8/v1.0/lrs/spectrum/info"
    request = Request(
        f"{base_url}?{urlencode({'obsid': obsid})}",
        headers={
            "User-Agent": "HOU-COMPACT/1.2 public spectrum-time contract",
            "Accept": "application/json,*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )
    status, final_url, content_type, disposition, raw = _open_bounded(
        opener,
        request,
        timeout=timeout,
        maximum_bytes=8 * 1024 * 1024,
    )
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SpectrumTimeContractError(
            "info_not_json", "spectrum-info response was not valid JSON"
        ) from error
    contract = _inspect_json(raw, expected_obsid=obsid)
    contract.update(
        {
            "http_status": status,
            "content_type": content_type,
            "content_disposition_present": bool(disposition.strip()),
            "final_url_path": _safe_path(final_url),
            "response_bytes": len(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    return contract, payload


def _fetch_fits(
    opener: Any,
    *,
    obsid: str,
    info_payload: Any,
    timeout: float,
) -> tuple[bytes, dict[str, Any]]:
    base_url = "https://www.lamost.org/openapi/dr8/v1.0/lrs/spectrum/fits"
    candidates = [f"{base_url}?{urlencode({'obsid': obsid})}"]
    candidates.extend(_same_origin_followup_urls(info_payload, base_url=base_url))
    attempts: list[dict[str, Any]] = []
    for candidate in candidates[:20]:
        request = Request(
            candidate,
            headers={
                "User-Agent": "HOU-COMPACT/1.2 public spectrum-time contract",
                "Accept": "application/fits,application/octet-stream,*/*;q=0.1",
                "Accept-Encoding": "identity",
            },
        )
        try:
            status, final_url, content_type, disposition, raw = _open_bounded(
                opener,
                request,
                timeout=timeout,
                maximum_bytes=64 * 1024 * 1024,
            )
        except SpectrumTimeContractError as error:
            attempts.append(
                {
                    "status": "failure",
                    "error_code": error.code,
                    "requested_path": _safe_path(candidate),
                }
            )
            continue
        is_fits = raw.startswith(_FITS_MAGIC)
        attempts.append(
            {
                "status": "success" if is_fits else "non_fits",
                "http_status": status,
                "requested_path": _safe_path(candidate),
                "final_url_path": _safe_path(final_url),
                "content_type": content_type,
                "content_disposition_present": bool(disposition.strip()),
                "response_bytes": len(raw),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "fits_magic": is_fits,
            }
        )
        if is_fits:
            return raw, {"attempts": attempts, "successful_attempt_index": len(attempts) - 1}
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for followup in _same_origin_followup_urls(payload, base_url=final_url):
            if followup not in candidates and len(candidates) < 20:
                candidates.append(followup)
    raise SpectrumTimeContractError(
        "fits_unavailable", "no bounded first-party response exposed a FITS file"
    )


def _inspect_fits_header(raw: bytes, *, expected_obsid: str) -> dict[str, Any]:
    try:
        with fits.open(
            io.BytesIO(raw),
            memmap=False,
            do_not_scale_image_data=True,
            ignore_missing_end=False,
        ) as hdul:
            header = hdul[0].header
            keyword_count = len([key for key in header.keys() if key])
            obsid_value = header.get("OBSID")
            obsid_matches = str(obsid_value).strip() == expected_obsid
            present = [key for key in _FITS_REVIEW_KEYS if key in header]
            shapes = {key: _scalar_shape(header[key]) for key in present if key != "OBSID"}
    except Exception as error:
        raise SpectrumTimeContractError(
            "fits_parse", f"FITS header parsing failed: {type(error).__name__}"
        ) from error

    date_obs_shape = shapes.get("DATE-OBS", {"type": "missing"})
    date_obs_precise = bool(date_obs_shape.get("iso_datetime"))
    return {
        "primary_header_keyword_count": keyword_count,
        "review_keywords_present": present,
        "header_obsid_present": "OBSID" in present,
        "header_obsid_matches_requested": obsid_matches,
        "time_keyword_shapes": shapes,
        "date_obs_is_iso_datetime": date_obs_precise,
        "precise_observation_midpoint_available": obsid_matches and date_obs_precise,
        "time_semantics": {
            "DATE-OBS": "official DR8 LRS documentation defines this as median observation UTC",
            "DATE": "file creation UTC; deliberately excluded from observation-time assessment",
        },
    }


def probe(*, output: Path, timeout: float = 180.0) -> dict[str, Any]:
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    _, obsid, discovery = _fetch_sample_and_obsid(opener, timeout=timeout)
    info_contract, info_payload = _fetch_info(opener, obsid=obsid, timeout=timeout)
    fits_raw, fits_transport = _fetch_fits(
        opener,
        obsid=obsid,
        info_payload=info_payload,
        timeout=timeout,
    )
    header_contract = _inspect_fits_header(fits_raw, expected_obsid=obsid)
    status = (
        "success"
        if header_contract["precise_observation_midpoint_available"]
        else "failure"
    )
    result = {
        "schema_version": "0.1",
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
                "FITS DATE-OBS must agree with all MEC-matched candidate obsids before "
                "it may fill MEC-missing candidate times"
            ),
        },
        "privacy_contract": (
            "No sample Gaia ID, obsid, filename, coordinate, RV, URL query, timestamp value, "
            "or FITS payload is persisted. Only aggregate shapes, hashes, generic paths, and "
            "exact-identity booleans are retained."
        ),
        "claim_boundary": (
            "A public FITS-header timing contract only enables a private exact-time bridge. "
            "It does not validate an RV, orbit, companion, or compact-object candidate."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if status != "success":
        raise SpectrumTimeContractError(
            "precise_time_unavailable", "public FITS header lacked exact obsid-linked DATE-OBS"
        )
    return result


def _write_failure(output: Path, error: Exception) -> dict[str, Any]:
    code = error.code if isinstance(error, SpectrumTimeContractError) else "unexpected_error"
    message = (
        str(error)
        if isinstance(error, SpectrumTimeContractError)
        else f"unexpected probe failure: {type(error).__name__}"
    )
    result = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "error_code": code,
        "safe_error": message,
        "privacy_contract": (
            "Failure output contains no sample Gaia ID, obsid, coordinate, RV, timestamp, "
            "filename, URL query, or response row."
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
        result = _write_failure(args.output, error)
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "candidate_safe": True,
                "status": result["status"],
                "fits_header_contract": result["fits_header_contract"],
                "replacement_assessment": result["replacement_assessment"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
