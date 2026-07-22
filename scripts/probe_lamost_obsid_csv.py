#!/usr/bin/env python3
"""Validate the public LAMOST exact-obsid CSV form with an official sample obsid.

The sample obsid is fetched from LAMOST's own public ``u/obsid.txt`` example. Its
value is used only in the HTTPS request and is never printed or persisted. The
artifact records response metadata, header names, row counts, hashes, and redacted
same-origin follow-up paths only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.cookiejar
import json
import re
import secrets
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

_EXACT_OBSID = re.compile(r"^[0-9]+$")
_REQUIRED_COLUMNS = {"obsid", "rv", "rv_err", "fibermask"}
_OUTPUT_COLUMNS = (
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
    "gaia_source_id",
)


class ObsidCsvProbeError(RuntimeError):
    """Raised when the official exact-obsid CSV contract cannot be verified."""


class LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attributes = {str(key).lower(): "" if value is None else str(value) for key, value in attrs}
        href = attributes.get("href", "").strip()
        if href:
            self.links.append(urljoin(self.base_url, href))


def _bounded_read(response, maximum_bytes: int) -> bytes:
    raw = response.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise ObsidCsvProbeError("response exceeded configured byte ceiling")
    return raw


def _safe_url_metadata(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    redacted = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return {
        "origin_and_path": redacted,
        "full_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
    }


def _multipart_body(fields: Iterable[tuple[str, str]], boundary: str) -> bytes:
    pieces: list[bytes] = []
    for name, value in fields:
        if any(token in name for token in ("\r", "\n", '"')):
            raise ValueError("multipart field name contains unsafe characters")
        pieces.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    pieces.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(pieces)


def _parse_delimited(raw: bytes) -> tuple[str, list[str], int, list[list[str]]] | None:
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    candidates: list[tuple[int, str, list[list[str]]]] = []
    for delimiter in (",", "|", "\t"):
        try:
            rows = list(csv.reader(lines, delimiter=delimiter, strict=True))
        except csv.Error:
            continue
        if not rows or len(rows[0]) < 2:
            continue
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            continue
        candidates.append((width, delimiter, rows))
    if not candidates:
        return None
    maximum = max(item[0] for item in candidates)
    winners = [item for item in candidates if item[0] == maximum]
    if len(winners) != 1:
        return None
    _, delimiter, rows = winners[0]
    columns = [value.strip().lower().lstrip("\ufeff") for value in rows[0]]
    if any(not value for value in columns) or len(set(columns)) != len(columns):
        return None
    return delimiter, columns, max(0, len(rows) - 1), rows[1:]


def _same_origin_candidates(html: bytes, base_url: str) -> list[str]:
    try:
        text = html.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        return []
    parser = LinkParser(base_url)
    parser.feed(text)
    parser.close()
    base = urlparse(base_url)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for link in parser.links:
        parsed = urlparse(link)
        if parsed.scheme != "https" or parsed.netloc != base.netloc:
            continue
        if link in seen:
            continue
        seen.add(link)
        lower = link.lower()
        score = 0
        score += 5 if ".csv" in lower else 0
        score += 4 if "download" in lower else 0
        score += 3 if "export" in lower else 0
        score += 2 if "result" in lower else 0
        score += 1 if "/q" in parsed.path else 0
        if score:
            scored.append((score, link))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [link for _, link in scored[:8]]


def _fetch_official_sample(opener, sample_url: str, timeout: float) -> tuple[str, dict[str, object]]:
    request = Request(
        sample_url,
        headers={
            "User-Agent": "HOU-COMPACT/0.5 LAMOST official sample contract",
            "Accept": "text/plain,*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        raw = _bounded_read(response, 65536)
        final_url = str(getattr(response, "geturl", lambda: sample_url)())
    if status != 200:
        raise ObsidCsvProbeError(f"official sample returned HTTP {status}")
    text = raw.decode("utf-8-sig", errors="strict")
    obsids = [token for token in re.split(r"[\s,;]+", text) if token]
    exact = [token for token in obsids if _EXACT_OBSID.fullmatch(token)]
    if not exact:
        raise ObsidCsvProbeError("official sample contains no exact obsid")
    return exact[0], {
        "http_status": status,
        "sample_file_bytes": len(raw),
        "sample_file_sha256": hashlib.sha256(raw).hexdigest(),
        "sample_exact_obsid_count": len(exact),
        "selected_obsid_sha256": hashlib.sha256(exact[0].encode("ascii")).hexdigest(),
        "final_url": _safe_url_metadata(final_url),
    }


def probe(
    *,
    action_url: str,
    sample_url: str,
    output_path: Path,
    timeout: float = 180.0,
    maximum_response_bytes: int = 8 * 1024 * 1024,
) -> dict[str, object]:
    if not action_url.startswith("https://") or not sample_url.startswith("https://"):
        raise ValueError("all URLs must use HTTPS")
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    obsid, sample_receipt = _fetch_official_sample(opener, sample_url, timeout)

    fields: list[tuple[str, str]] = [
        ("sForm", "0"),
        ("pos.type", "none"),
        ("obsidTextarea", obsid),
        ("output.collection", "minimal"),
        ("output.fmt", "csv"),
    ]
    fields.extend((f"output.combined.{column}", "on") for column in _OUTPUT_COLUMNS)
    fields.append(("sBtn", "Search"))
    boundary = "----HOUCOMPACT" + secrets.token_hex(16)
    body = _multipart_body(fields, boundary)
    request = Request(
        action_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "HOU-COMPACT/0.5 LAMOST exact-obsid CSV contract",
            "Accept": "text/csv,text/plain,text/html,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Origin": "https://www.lamost.org",
            "Referer": "https://www.lamost.org/dr8/v1.0/search",
        },
        method="POST",
    )
    with opener.open(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        raw = _bounded_read(response, maximum_response_bytes)
        content_type = str(response.headers.get("Content-Type", ""))
        disposition = str(response.headers.get("Content-Disposition", ""))
        final_url = str(getattr(response, "geturl", lambda: action_url)())

    attempts: list[dict[str, object]] = [
        {
            "kind": "form_post",
            "http_status": status,
            "content_type": content_type,
            "content_disposition": disposition,
            "response_bytes": len(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "final_url": _safe_url_metadata(final_url),
        }
    ]
    parsed = _parse_delimited(raw)
    if parsed is None:
        for link in _same_origin_candidates(raw, final_url):
            follow_request = Request(
                link,
                headers={
                    "User-Agent": "HOU-COMPACT/0.5 LAMOST exact-obsid CSV contract",
                    "Accept": "text/csv,text/plain,*/*;q=0.1",
                    "Accept-Encoding": "identity",
                    "Referer": final_url,
                },
            )
            with opener.open(follow_request, timeout=timeout) as response:
                follow_status = int(getattr(response, "status", 200))
                follow_raw = _bounded_read(response, maximum_response_bytes)
                follow_type = str(response.headers.get("Content-Type", ""))
                follow_disposition = str(response.headers.get("Content-Disposition", ""))
                follow_final = str(getattr(response, "geturl", lambda: link)())
            attempts.append(
                {
                    "kind": "same_origin_followup",
                    "http_status": follow_status,
                    "content_type": follow_type,
                    "content_disposition": follow_disposition,
                    "response_bytes": len(follow_raw),
                    "response_sha256": hashlib.sha256(follow_raw).hexdigest(),
                    "final_url": _safe_url_metadata(follow_final),
                }
            )
            candidate = _parse_delimited(follow_raw)
            if candidate is not None:
                raw = follow_raw
                parsed = candidate
                break

    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "official_sample": sample_receipt,
        "form_contract": {
            "action": _safe_url_metadata(action_url),
            "method": "POST",
            "enctype": "multipart/form-data",
            "obsid_control": "obsidTextarea",
            "format_control": "output.fmt=csv",
            "selected_output_columns": list(_OUTPUT_COLUMNS),
            "multipart_field_count": len(fields),
            "multipart_body_bytes": len(body),
            "multipart_body_sha256": hashlib.sha256(body).hexdigest(),
        },
        "response_attempts": attempts,
        "claim_boundary": (
            "The request uses one public LAMOST sample obsid. No HOU-COMPACT candidate "
            "obsid, Gaia source identifier, coordinate, RV value, or response row is "
            "stored or printed."
        ),
    }
    if parsed is None:
        payload["status"] = "failure"
        payload["error"] = "no bounded response exposed a valid delimited table"
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        raise ObsidCsvProbeError(str(payload["error"]))

    delimiter, columns, row_count, rows = parsed
    missing = sorted(_REQUIRED_COLUMNS - set(columns))
    obsid_index = columns.index("obsid") if "obsid" in columns else None
    exact_match_count = 0
    if obsid_index is not None:
        for row in rows:
            if obsid_index < len(row) and row[obsid_index].strip() == obsid:
                exact_match_count += 1
    payload.update(
        {
            "status": "success" if not missing and exact_match_count >= 1 else "failure",
            "table_contract": {
                "delimiter": delimiter,
                "column_count": len(columns),
                "columns": columns,
                "data_row_count": row_count,
                "required_columns_present": not missing,
                "missing_required_columns": missing,
                "official_sample_exact_match_count": exact_match_count,
                "table_response_sha256": hashlib.sha256(raw).hexdigest(),
            },
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if payload["status"] != "success":
        raise ObsidCsvProbeError("CSV response failed required-column or exact-obsid checks")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--action-url",
        default="https://www.lamost.org/dr8/v1.0/q",
    )
    parser.add_argument(
        "--sample-url",
        default="https://www.lamost.org/dr8/v1.0/u/obsid.txt",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("lamost_obsid_csv_contract.json"),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = probe(
        action_url=args.action_url,
        sample_url=args.sample_url,
        output_path=args.output,
        timeout=args.timeout,
    )
    safe = {
        "status": payload["status"],
        "response_attempt_count": len(payload["response_attempts"]),
        "table_contract": payload.get("table_contract"),
        "candidate_safe": True,
    }
    print(json.dumps(safe, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
