#!/usr/bin/env python3
"""Fingerprint the first-party LAMOST response to a non-existent Gaia DR2 ID.

No HOU-COMPACT identifier is submitted. The fixed probe value is outside the Gaia
DR2 source-id range and is never stored in the artifact. Raw response content is not
persisted; only hashes, sizes and generic marker booleans are recorded.
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

_PROBE_ID = "9999999999999999999"
_OUTPUT = ("gaia_source_id", "obsid", "lmjd", "rv", "rv_err", "fibermask")
_MARKERS = (
    "no result",
    "no record",
    "not found",
    "zero result",
    "0 result",
    "empty result",
    "gaiasourcearea",
    "output.fmt",
    "search",
    "error",
    "limit",
)


def probe(*, output: Path, timeout: float = 180.0) -> dict[str, object]:
    search_url = "https://www.lamost.org/dr8/v1.0/search"
    action_url = "https://www.lamost.org/dr8/v1.0/q"
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    search = Request(
        search_url,
        headers={
            "User-Agent": "HOU-COMPACT/0.9 LAMOST zero-result contract",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    with opener.open(search, timeout=timeout) as response:
        search_status = int(getattr(response, "status", 200))
        search_raw = _bounded_read(response, 8 * 1024 * 1024)

    fields: list[tuple[str, str]] = [
        ("sForm", "0"),
        ("pos.type", "none"),
        ("gaiasourcearea", _PROBE_ID),
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
            "User-Agent": "HOU-COMPACT/0.9 LAMOST zero-result contract",
            "Accept": "text/csv,text/plain,text/html,*/*;q=0.1",
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
        final_url = str(response.geturl())
        raw = _bounded_read(response, 16 * 1024 * 1024)

    parsed = normalize_parsed_table(
        _parse_delimited(raw, source_kind="form_post", source_url=final_url)
    )
    lower = raw[:1_000_000].decode("utf-8-sig", errors="replace").lower()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", lower, flags=re.DOTALL)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "success",
        "probe_contract": {
            "fixed_non_candidate_id_sha256": hashlib.sha256(
                _PROBE_ID.encode("ascii")
            ).hexdigest(),
            "input_control": "gaiasourcearea",
            "method": "POST",
            "format": "csv",
            "selected_output_columns": list(_OUTPUT),
            "multipart_body_bytes": len(body),
            "multipart_body_sha256": hashlib.sha256(body).hexdigest(),
            "search_http_status": search_status,
            "search_response_sha256": hashlib.sha256(search_raw).hexdigest(),
        },
        "response_contract": {
            "http_status": status,
            "content_type": content_type,
            "content_disposition_present": bool(disposition),
            "final_url_path": re.sub(r"[?#].*$", "", final_url),
            "response_bytes": len(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "parsed_delimited_table": parsed is not None,
            "delimiter": parsed.delimiter if parsed is not None else None,
            "columns": list(parsed.columns) if parsed is not None else [],
            "data_row_count": len(parsed.rows) if parsed is not None else None,
            "html_present": "<html" in lower or "<!doctype html" in lower,
            "title_present": bool(title),
            "title_length": len(title),
            "title_sha256": hashlib.sha256(title.encode("utf-8")).hexdigest()
            if title
            else None,
            "generic_marker_presence": {
                marker.replace(" ", "_"): marker in lower for marker in _MARKERS
            },
        },
        "claim_boundary": (
            "A fixed non-existent public test value only. No HOU-COMPACT identifier, "
            "coordinate, RV value, response row, raw HTML, or title text is retained."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("lamost_gaia_zero_result_contract.json")
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    payload = probe(output=args.output, timeout=args.timeout)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
