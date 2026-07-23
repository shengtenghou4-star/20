#!/usr/bin/env python3
"""Validate exact Gaia DR2 ID form queries with a first-party public sample.

The sample identifier is fetched from LAMOST's own public file and is never printed
or persisted. Only aggregate response metadata, normalized headers, row counts and
hashes are written.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import re
import secrets
from pathlib import Path
from urllib.request import HTTPCookieProcessor, Request, build_opener

from hou_compact.lamost_form_rv import _bounded_read, _multipart_body, _parse_delimited
from hou_compact.lamost_form_rv_v2 import normalize_parsed_table

_EXACT_SOURCE = re.compile(r"^[0-9]{10,20}$")
_REQUIRED = {"gaia_source_id", "obsid", "rv", "rv_err", "fibermask"}
_OUTPUT = (
    "gaia_source_id",
    "obsid",
    "lmjd",
    "mjd",
    "obsdate",
    "rv",
    "rv_err",
    "snrg",
    "snri",
    "class",
    "subclass",
    "fibermask",
)


class GaiaFormProbeError(RuntimeError):
    pass


def _fetch_sample(opener, url: str, timeout: float) -> tuple[str, dict[str, object]]:
    request = Request(
        url,
        headers={
            "User-Agent": "HOU-COMPACT/0.7 LAMOST Gaia DR2 sample contract",
            "Accept": "text/plain,*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        raw = _bounded_read(response, 65536)
    if status != 200:
        raise GaiaFormProbeError(f"official sample returned HTTP {status}")
    tokens = [token for token in re.split(r"[\s,;]+", raw.decode("utf-8-sig")) if token]
    exact = [token for token in tokens if _EXACT_SOURCE.fullmatch(token)]
    if not exact:
        raise GaiaFormProbeError("official sample contains no exact Gaia DR2 source ID")
    selected = exact[0]
    return selected, {
        "http_status": status,
        "sample_file_bytes": len(raw),
        "sample_file_sha256": hashlib.sha256(raw).hexdigest(),
        "sample_exact_id_count": len(exact),
        "selected_id_sha256": hashlib.sha256(selected.encode("ascii")).hexdigest(),
    }


def probe(*, output: Path, timeout: float = 180.0) -> dict[str, object]:
    search_url = "https://www.lamost.org/dr8/v1.0/search"
    action_url = "https://www.lamost.org/dr8/v1.0/q"
    sample_url = "https://www.lamost.org/dr8/v1.0/u/gaia_source_id.txt"
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    sample, sample_receipt = _fetch_sample(opener, sample_url, timeout)
    search_request = Request(
        search_url,
        headers={
            "User-Agent": "HOU-COMPACT/0.7 exact Gaia DR2 form contract",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    with opener.open(search_request, timeout=timeout) as response:
        search_status = int(getattr(response, "status", 200))
        search_raw = _bounded_read(response, 8 * 1024 * 1024)
    if search_status != 200:
        raise GaiaFormProbeError(f"search page returned HTTP {search_status}")

    fields: list[tuple[str, str]] = [
        ("sForm", "0"),
        ("pos.type", "none"),
        ("gaiasourcearea", sample),
        ("output.collection", "minimal"),
        ("output.fmt", "csv"),
    ]
    fields.extend((f"output.combined.{column}", "on") for column in _OUTPUT)
    fields.append(("sBtn", "Search"))
    boundary = "----HOUCOMPACT" + secrets.token_hex(16)
    body = _multipart_body(fields, boundary)
    request = Request(
        action_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "HOU-COMPACT/0.7 exact Gaia DR2 form contract",
            "Accept": "text/csv,text/plain,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Origin": "https://www.lamost.org",
            "Referer": search_url,
        },
        method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        content_type = str(response.headers.get("Content-Type", ""))
        disposition = str(response.headers.get("Content-Disposition", ""))
        raw = _bounded_read(response, 16 * 1024 * 1024)
    if status != 200:
        raise GaiaFormProbeError(f"form returned HTTP {status}")

    parsed = normalize_parsed_table(
        _parse_delimited(raw, source_kind="form_post", source_url=action_url)
    )
    if parsed is None:
        raise GaiaFormProbeError("form response is not a bounded delimited table")
    missing = sorted(_REQUIRED - set(parsed.columns))
    gaia_index = parsed.columns.index("gaia_source_id") if "gaia_source_id" in parsed.columns else -1
    exact_rows = 0
    outside_rows = 0
    if gaia_index >= 0:
        for row in parsed.rows:
            token = row[gaia_index].strip()
            exact_rows += int(token == sample)
            outside_rows += int(token != sample)

    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "success" if not missing and exact_rows >= 1 and outside_rows == 0 else "failure",
        "official_sample": sample_receipt,
        "request_contract": {
            "method": "POST",
            "input_control": "gaiasourcearea",
            "format": "csv",
            "collection": "minimal",
            "selected_output_columns": list(_OUTPUT),
            "multipart_field_count": len(fields),
            "multipart_body_bytes": len(body),
            "multipart_body_sha256": hashlib.sha256(body).hexdigest(),
            "search_page_sha256": hashlib.sha256(search_raw).hexdigest(),
        },
        "response_contract": {
            "http_status": status,
            "content_type": content_type,
            "content_disposition_present": bool(disposition),
            "response_bytes": len(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "delimiter": parsed.delimiter,
            "columns": list(parsed.columns),
            "column_count": len(parsed.columns),
            "data_row_count": len(parsed.rows),
            "missing_required_columns": missing,
            "exact_sample_rows": exact_rows,
            "rows_outside_sample_id": outside_rows,
        },
        "claim_boundary": (
            "One public first-party sample Gaia DR2 ID only. No HOU-COMPACT candidate "
            "identifier, coordinate, RV value, or response row is persisted or printed."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if payload["status"] != "success":
        raise GaiaFormProbeError("Gaia DR2 form response failed exact-ID or column checks")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("lamost_gaia_dr2_form_contract.json"))
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    payload = probe(output=args.output, timeout=args.timeout)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "candidate_safe": True,
                "response_contract": payload["response_contract"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
