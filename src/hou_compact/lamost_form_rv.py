"""Bounded exact-obsid client for the public LAMOST DR8 search form.

This module submits batches of exact integer ``obsid`` values to the first-party
LAMOST search form and validates the returned delimited table before writing it.
It deliberately stores no candidate identifiers in the candidate-safe summary.
Source-level output and the private manifest are intended for an encrypted private
relay.
"""

from __future__ import annotations

import csv
import hashlib
import http.cookiejar
import json
import re
import secrets
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

_EXACT_OBSID = re.compile(r"^[0-9]+$")
_REQUIRED_COLUMNS = ("obsid", "rv", "rv_err", "fibermask")
_DEFAULT_OUTPUT_COLUMNS = (
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


class LamostFormError(RuntimeError):
    """Raised when the public form response violates a frozen safety contract."""


@dataclass(frozen=True)
class ParsedTable:
    delimiter: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    response_sha256: str
    response_bytes: int
    source_kind: str
    source_url_path: str


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        mapping = {
            str(key).lower(): "" if value is None else str(value)
            for key, value in attrs
        }
        href = mapping.get("href", "").strip()
        if href:
            self.links.append(urljoin(self.base_url, href))


def _safe_path(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _chunks(values: Sequence[str], size: int) -> Iterator[tuple[str, ...]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])


def load_exact_obsids(path: Path, *, column: str = "obsid") -> tuple[str, ...]:
    """Load exact, unique obsids from CSV without numeric coercion."""

    if not path.exists() or path.stat().st_size == 0:
        raise LamostFormError("obsid input is missing or empty")
    obsids: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        if not reader.fieldnames:
            raise LamostFormError("obsid input has no header")
        normalized = {
            str(name).strip().lower().lstrip("\ufeff"): str(name)
            for name in reader.fieldnames
        }
        source_column = normalized.get(column.strip().lower())
        if source_column is None:
            raise LamostFormError(f"obsid input is missing column {column!r}")
        for row in reader:
            if None in row:
                raise LamostFormError("obsid input row has extra fields")
            token = "" if row.get(source_column) is None else str(row[source_column])
            if token != token.strip() or not _EXACT_OBSID.fullmatch(token):
                raise LamostFormError("obsid input contains a non-exact integer token")
            if token in seen:
                raise LamostFormError("obsid input repeats an obsid")
            seen.add(token)
            obsids.append(token)
    if not obsids:
        raise LamostFormError("obsid input contains no rows")
    return tuple(sorted(obsids, key=lambda value: (len(value), value)))


def _multipart_body(fields: Iterable[tuple[str, str]], boundary: str) -> bytes:
    pieces: list[bytes] = []
    for name, value in fields:
        if any(token in name for token in ("\r", "\n", '"')):
            raise ValueError("multipart field name contains unsafe characters")
        pieces.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(
                    "ascii"
                ),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    pieces.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(pieces)


def _bounded_read(response: Any, maximum_bytes: int) -> bytes:
    raw = response.read(maximum_bytes + 1)
    if len(raw) > maximum_bytes:
        raise LamostFormError("LAMOST response exceeded configured byte ceiling")
    return raw


def _parse_delimited(raw: bytes, *, source_kind: str, source_url: str) -> ParsedTable | None:
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
    columns = tuple(value.strip().lower().lstrip("\ufeff") for value in rows[0])
    if any(not value for value in columns) or len(set(columns)) != len(columns):
        return None
    return ParsedTable(
        delimiter=delimiter,
        columns=columns,
        rows=tuple(tuple(value for value in row) for row in rows[1:]),
        response_sha256=hashlib.sha256(raw).hexdigest(),
        response_bytes=len(raw),
        source_kind=source_kind,
        source_url_path=_safe_path(source_url),
    )


def _same_origin_followups(raw: bytes, *, base_url: str, limit: int = 8) -> list[str]:
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        return []
    parser = _LinkParser(base_url)
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
        score += 8 if ".csv" in lower else 0
        score += 6 if "download" in lower else 0
        score += 4 if "export" in lower else 0
        score += 2 if "result" in lower else 0
        score += 1 if "/q" in parsed.path else 0
        if score:
            scored.append((score, link))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [link for _, link in scored[:limit]]


def _validate_table(
    table: ParsedTable,
    *,
    requested_obsids: set[str],
    expected_columns: tuple[str, ...] | None,
) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    missing = sorted(set(_REQUIRED_COLUMNS) - set(table.columns))
    if missing:
        raise LamostFormError(f"LAMOST response is missing columns: {missing}")
    if expected_columns is not None and table.columns != expected_columns:
        raise LamostFormError("LAMOST response header changed between batches")
    obsid_index = table.columns.index("obsid")
    seen: set[str] = set()
    records: list[dict[str, str]] = []
    for row in table.rows:
        obsid = row[obsid_index]
        if obsid != obsid.strip() or not _EXACT_OBSID.fullmatch(obsid):
            raise LamostFormError("LAMOST response contains a non-exact obsid")
        if obsid not in requested_obsids:
            raise LamostFormError("LAMOST response contains an obsid outside the batch")
        if obsid in seen:
            raise LamostFormError("LAMOST response repeats an obsid within one batch")
        seen.add(obsid)
        records.append(dict(zip(table.columns, row)))
    return records, table.columns


def _open_bounded(opener: Any, request: Request, *, timeout: float, maximum_bytes: int) -> tuple[int, str, str, bytes]:
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            final_url = str(getattr(response, "geturl", lambda: request.full_url)())
            content_type = str(response.headers.get("Content-Type", ""))
            raw = _bounded_read(response, maximum_bytes)
    except HTTPError as error:
        raise LamostFormError(f"LAMOST form returned HTTP {error.code}") from error
    except URLError as error:
        raise LamostFormError(f"LAMOST form transport failed: {error.reason}") from error
    if status != 200:
        raise LamostFormError(f"LAMOST form returned HTTP {status}")
    return status, final_url, content_type, raw


def _fetch_batch(
    opener: Any,
    *,
    action_url: str,
    referer_url: str,
    obsids: tuple[str, ...],
    output_columns: tuple[str, ...],
    collection: str,
    timeout: float,
    maximum_response_bytes: int,
) -> tuple[ParsedTable, list[dict[str, object]]]:
    boundary = "----HOUCOMPACT" + secrets.token_hex(16)
    fields: list[tuple[str, str]] = [
        ("sForm", "0"),
        ("pos.type", "none"),
        ("obsidTextarea", "\n".join(obsids)),
        ("output.collection", collection),
        ("output.fmt", "csv"),
    ]
    fields.extend((f"output.combined.{column}", "on") for column in output_columns)
    fields.append(("sBtn", "Search"))
    body = _multipart_body(fields, boundary)
    request = Request(
        action_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "HOU-COMPACT/0.6 exact-obsid LAMOST form client",
            "Accept": "text/csv,text/plain,text/html,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Origin": f"{urlparse(action_url).scheme}://{urlparse(action_url).netloc}",
            "Referer": referer_url,
        },
        method="POST",
    )
    status, final_url, content_type, raw = _open_bounded(
        opener,
        request,
        timeout=timeout,
        maximum_bytes=maximum_response_bytes,
    )
    receipts: list[dict[str, object]] = [
        {
            "kind": "form_post",
            "http_status": status,
            "content_type": content_type,
            "response_bytes": len(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "final_url_path": _safe_path(final_url),
        }
    ]
    direct = _parse_delimited(raw, source_kind="form_post", source_url=final_url)
    if direct is not None:
        return direct, receipts
    for link in _same_origin_followups(raw, base_url=final_url):
        follow = Request(
            link,
            headers={
                "User-Agent": "HOU-COMPACT/0.6 exact-obsid LAMOST form client",
                "Accept": "text/csv,text/plain,*/*;q=0.1",
                "Accept-Encoding": "identity",
                "Referer": final_url,
            },
        )
        follow_status, follow_url, follow_type, follow_raw = _open_bounded(
            opener,
            follow,
            timeout=timeout,
            maximum_bytes=maximum_response_bytes,
        )
        receipts.append(
            {
                "kind": "same_origin_followup",
                "http_status": follow_status,
                "content_type": follow_type,
                "response_bytes": len(follow_raw),
                "response_sha256": hashlib.sha256(follow_raw).hexdigest(),
                "final_url_path": _safe_path(follow_url),
            }
        )
        parsed = _parse_delimited(
            follow_raw,
            source_kind="same_origin_followup",
            source_url=follow_url,
        )
        if parsed is not None:
            return parsed, receipts
    raise LamostFormError("LAMOST form exposed no bounded delimited result")


def acquire_form_rv(
    *,
    obsid_input: Path,
    output_path: Path,
    private_manifest_path: Path,
    safe_summary_path: Path,
    search_url: str = "https://www.lamost.org/dr8/v1.0/search",
    action_url: str = "https://www.lamost.org/dr8/v1.0/q",
    obsid_column: str = "obsid",
    batch_size: int = 100,
    collection: str = "typical",
    output_columns: tuple[str, ...] = _DEFAULT_OUTPUT_COLUMNS,
    timeout: float = 180.0,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    retries: int = 2,
    opener: Any | None = None,
    sleep: Any = time.sleep,
) -> dict[str, object]:
    """Acquire exact-observation RV rows and write private/safe audit records."""

    if not search_url.startswith("https://") or not action_url.startswith("https://"):
        raise ValueError("LAMOST URLs must use HTTPS")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if maximum_response_bytes < 1024:
        raise ValueError("maximum_response_bytes must be at least 1024")
    if retries < 1:
        raise ValueError("retries must be positive")
    obsids = load_exact_obsids(obsid_input, column=obsid_column)
    if opener is None:
        jar = http.cookiejar.CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))

    # Establish the same first-party session/cookie context as a browser search.
    search_request = Request(
        search_url,
        headers={
            "User-Agent": "HOU-COMPACT/0.6 exact-obsid LAMOST form client",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    search_status, search_final, search_type, search_raw = _open_bounded(
        opener,
        search_request,
        timeout=timeout,
        maximum_bytes=8 * 1024 * 1024,
    )
    private_manifest: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_sensitive": True,
        "status": "started",
        "input_obsid_count": len(obsids),
        "batch_size": batch_size,
        "collection": collection,
        "output_columns": list(output_columns),
        "search_session": {
            "http_status": search_status,
            "content_type": search_type,
            "response_bytes": len(search_raw),
            "response_sha256": hashlib.sha256(search_raw).hexdigest(),
            "final_url_path": _safe_path(search_final),
        },
        "batches": [],
    }
    safe_summary: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "started",
        "input_obsid_count": len(obsids),
        "batch_size": batch_size,
        "batch_count": 0,
        "returned_unique_obsids": 0,
        "missing_obsids": 0,
        "columns": None,
        "claim_boundary": (
            "This summary reports bounded first-party exact-obsid acquisition only. "
            "No obsid, Gaia identifier, coordinate, RV value, or source-level row is disclosed."
        ),
    }

    def write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
    expected_columns: tuple[str, ...] | None = None
    all_returned: set[str] = set()
    writer_handle = None
    try:
        writer_handle = temporary_output.open("w", encoding="utf-8", newline="")
        writer: csv.DictWriter | None = None
        for batch_index, batch in enumerate(_chunks(obsids, batch_size), start=1):
            batch_receipt: dict[str, object] = {
                "batch_index": batch_index,
                "requested_count": len(batch),
                "status": "failure",
                "attempts": [],
            }
            last_error: Exception | None = None
            for attempt in range(1, retries + 1):
                try:
                    table, transport = _fetch_batch(
                        opener,
                        action_url=action_url,
                        referer_url=search_final,
                        obsids=batch,
                        output_columns=output_columns,
                        collection=collection,
                        timeout=timeout,
                        maximum_response_bytes=maximum_response_bytes,
                    )
                    records, columns = _validate_table(
                        table,
                        requested_obsids=set(batch),
                        expected_columns=expected_columns,
                    )
                    if expected_columns is None:
                        expected_columns = columns
                        writer = csv.DictWriter(
                            writer_handle,
                            fieldnames=list(columns),
                            extrasaction="raise",
                        )
                        writer.writeheader()
                    assert writer is not None
                    batch_returned: set[str] = set()
                    for record in records:
                        obsid = record["obsid"]
                        if obsid in all_returned:
                            raise LamostFormError(
                                "LAMOST response repeats an obsid across batches"
                            )
                        batch_returned.add(obsid)
                        all_returned.add(obsid)
                        writer.writerow(record)
                    batch_receipt.update(
                        {
                            "status": "success",
                            "successful_attempt": attempt,
                            "returned_count": len(records),
                            "missing_count": len(batch) - len(records),
                            "delimiter": table.delimiter,
                            "source_kind": table.source_kind,
                            "response_sha256": table.response_sha256,
                            "response_bytes": table.response_bytes,
                            "response_url_path": table.source_url_path,
                            "transport": transport,
                        }
                    )
                    last_error = None
                    break
                except Exception as error:  # bounded retry, receipt stores no IDs
                    last_error = error
                    batch_receipt["attempts"].append(
                        {
                            "attempt": attempt,
                            "error_type": type(error).__name__,
                            "error": str(error)[:1000],
                        }
                    )
                    if attempt < retries:
                        sleep(min(10, attempt * 2))
            private_manifest["batches"].append(batch_receipt)
            write_json(private_manifest_path, private_manifest)
            if last_error is not None:
                raise last_error

        writer_handle.flush()
        writer_handle.close()
        writer_handle = None
        temporary_output.replace(output_path)
        safe_summary.update(
            {
                "status": "success",
                "batch_count": len(private_manifest["batches"]),
                "returned_unique_obsids": len(all_returned),
                "missing_obsids": len(obsids) - len(all_returned),
                "columns": list(expected_columns or ()),
            }
        )
        private_manifest.update(
            {
                "status": "success",
                "returned_unique_obsids": len(all_returned),
                "missing_obsids": len(obsids) - len(all_returned),
                "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            }
        )
        write_json(private_manifest_path, private_manifest)
        write_json(safe_summary_path, safe_summary)
        return safe_summary
    except Exception as error:
        if writer_handle is not None:
            writer_handle.close()
        temporary_output.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
        private_manifest.update(
            {
                "status": "failure",
                "error_type": type(error).__name__,
                "error": str(error)[:2000],
            }
        )
        safe_summary.update(
            {
                "status": "failure",
                "batch_count": len(private_manifest["batches"]),
                "returned_unique_obsids": len(all_returned),
                "missing_obsids": len(obsids) - len(all_returned),
                "error_type": type(error).__name__,
                "error": str(error)[:1000],
            }
        )
        write_json(private_manifest_path, private_manifest)
        write_json(safe_summary_path, safe_summary)
        raise
