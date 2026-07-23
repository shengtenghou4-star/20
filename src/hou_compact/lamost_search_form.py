"""Bounded browser-compatible transport for the public LAMOST search form.

The DR8 website submits ``multipart/form-data`` to a public ``/q`` endpoint. This
module implements text-only multipart requests with cookies and redirect support.
Candidate-safe receipts omit all field names/values, coordinates, identifiers,
query tokens, response bodies, and final URL query strings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from http.cookiejar import CookieJar
import math
import re
import secrets
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


class LamostSearchFormError(RuntimeError):
    """Raised when a public search-form request violates the bounded contract."""

    def __init__(
        self,
        message: str,
        *,
        receipt: SearchFormReceipt | None = None,
    ) -> None:
        super().__init__(message)
        self.receipt = receipt


@dataclass(frozen=True)
class SearchFormReceipt:
    endpoint: str
    final_path: str
    status: int
    attempts: int
    request_bytes: int
    request_sha256: str
    response_bytes: int
    response_sha256: str
    content_type: str
    response_kind: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def encode_multipart_fields(
    fields: Iterable[tuple[str, object]],
    *,
    boundary: str,
) -> bytes:
    """Encode text fields as deterministic multipart form data."""

    if re.fullmatch(r"[A-Za-z0-9_-]{12,80}", boundary) is None:
        raise ValueError("unsafe multipart boundary")
    chunks: list[bytes] = []
    for name, raw_value in fields:
        field_name = str(name)
        if not field_name or any(character in field_name for character in ('"', "\r", "\n")):
            raise ValueError("unsafe multipart field name")
        value = str(raw_value)
        if "\x00" in value:
            raise ValueError("multipart values must not contain NUL")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'
                ).encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks)


def _response_kind(content_type: str, body: bytes) -> str:
    lowered_type = content_type.lower()
    preview = body[:8192].lstrip().lower()
    if "text/html" in lowered_type or preview.startswith(b"<!doctype html") or b"<html" in preview:
        return "html"
    if "text/csv" in lowered_type or "application/csv" in lowered_type:
        return "csv"
    if "json" in lowered_type or preview.startswith((b"{", b"[")):
        return "json"
    if "xml" in lowered_type or preview.startswith(b"<?xml"):
        return "xml"
    return "binary"


def _safe_final_path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path or "/"


def submit_search_form(
    endpoint: str,
    fields: Iterable[tuple[str, object]],
    *,
    timeout: float = 180.0,
    retries: int = 2,
    maximum_request_bytes: int = 2 * 1024 * 1024,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    opener: Any | None = None,
    boundary: str | None = None,
) -> tuple[bytes, str, SearchFormReceipt]:
    """Submit one bounded public search form and return raw response bytes."""

    if not endpoint.startswith("https://"):
        raise ValueError("search endpoint must use HTTPS")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_request_bytes < 1024 or maximum_response_bytes < 1024:
        raise ValueError("request and response limits must be at least 1024 bytes")
    actual_boundary = boundary or f"HouCompact{secrets.token_hex(16)}"
    body = encode_multipart_fields(fields, boundary=actual_boundary)
    if len(body) > maximum_request_bytes:
        raise ValueError("multipart search request exceeded the byte limit")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded public LAMOST form client",
            "Accept": "text/html,text/csv,application/json,*/*;q=0.1",
            "Content-Type": f"multipart/form-data; boundary={actual_boundary}",
        },
    )
    client = opener or build_opener(HTTPCookieProcessor(CookieJar()))
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with client.open(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("Content-Type", ""))
                final_url = str(getattr(response, "url", endpoint))
                response_body = response.read(maximum_response_bytes + 1)
            if len(response_body) > maximum_response_bytes:
                raise LamostSearchFormError("search-form response exceeded the byte limit")
            receipt = SearchFormReceipt(
                endpoint=endpoint,
                final_path=_safe_final_path(final_url),
                status=status,
                attempts=attempt + 1,
                request_bytes=len(body),
                request_sha256=hashlib.sha256(body).hexdigest(),
                response_bytes=len(response_body),
                response_sha256=hashlib.sha256(response_body).hexdigest(),
                content_type=content_type,
                response_kind=_response_kind(content_type, response_body),
            )
            if status != 200:
                raise LamostSearchFormError(
                    f"search form returned HTTP {status}",
                    receipt=receipt,
                )
            return response_body, final_url, receipt
        except HTTPError as error:
            last_error = error
            response_body = error.read(maximum_response_bytes + 1)
            receipt = SearchFormReceipt(
                endpoint=endpoint,
                final_path=_safe_final_path(str(getattr(error, "url", endpoint))),
                status=int(error.code),
                attempts=attempt + 1,
                request_bytes=len(body),
                request_sha256=hashlib.sha256(body).hexdigest(),
                response_bytes=min(len(response_body), maximum_response_bytes),
                response_sha256=hashlib.sha256(
                    response_body[:maximum_response_bytes]
                ).hexdigest(),
                content_type=str(error.headers.get("Content-Type", "")),
                response_kind=_response_kind(
                    str(error.headers.get("Content-Type", "")),
                    response_body[:maximum_response_bytes],
                ),
            )
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise LamostSearchFormError(
                    f"search form returned HTTP {error.code}",
                    receipt=receipt,
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise LamostSearchFormError(
                    f"search-form transport failed: {type(error).__name__}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise LamostSearchFormError(str(last_error))
