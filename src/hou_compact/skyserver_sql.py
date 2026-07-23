"""Bounded anonymous SDSS DR17 SkyServer SQL transport.

Receipts deliberately omit SQL text and row values.  They retain only the
public endpoint, response metadata, response/query hashes, and row bound.
Source-level query results must be encrypted by their caller before persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from io import BytesIO
import math
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


class SkyServerSQLError(RuntimeError):
    """Raised when an anonymous SkyServer SQL response violates the contract."""


@dataclass(frozen=True)
class SkyServerSQLReceipt:
    endpoint: str
    status: int
    attempts: int
    response_bytes: int
    content_type: str
    response_sha256: str
    query_sha256: str
    maximum_rows: int

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _parse_csv(body: bytes, content_type: str) -> pd.DataFrame:
    if not body:
        raise SkyServerSQLError("SkyServer returned an empty response")
    preview = body[:8192].lstrip().lower()
    if b"<html" in preview or b"<!doctype html" in preview:
        raise SkyServerSQLError("SkyServer returned HTML instead of CSV")
    if b"error" in preview and b"," not in preview:
        raise SkyServerSQLError("SkyServer returned a non-tabular error response")
    try:
        frame = pd.read_csv(BytesIO(body), comment="#", dtype="string")
    except (pd.errors.EmptyDataError, UnicodeDecodeError) as error:
        raise SkyServerSQLError(
            "SkyServer response could not be parsed as CSV"
        ) from error
    if frame.columns.empty:
        raise SkyServerSQLError("SkyServer CSV has no columns")
    return frame


def skyserver_sql_get(
    endpoint: str,
    query: str,
    *,
    maximum_rows: int,
    timeout: float = 180.0,
    retries: int = 2,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    maximum_url_characters: int = 16_000,
    opener: Any = urlopen,
) -> tuple[pd.DataFrame, SkyServerSQLReceipt]:
    """Execute one bounded anonymous SkyServer SQL GET request."""

    root = endpoint.rstrip("/")
    if not root.startswith("https://"):
        raise ValueError("SkyServer endpoint must use HTTPS")
    statement = query.strip()
    if not statement:
        raise ValueError("query must not be empty")
    if maximum_rows < 1 or maximum_rows > 500_000:
        raise ValueError("maximum_rows must lie in [1, 500000]")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 1024:
        raise ValueError("maximum_response_bytes must be at least 1024")
    if maximum_url_characters < 1024:
        raise ValueError("maximum_url_characters must be at least 1024")

    encoded = urlencode({"cmd": statement, "format": "csv"})
    request_url = f"{root}?{encoded}"
    if len(request_url) > maximum_url_characters:
        raise SkyServerSQLError("encoded SkyServer query exceeds the URL-length limit")
    request = Request(
        request_url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded SDSS SkyServer client",
            "Accept": "text/csv,text/plain,*/*;q=0.1",
        },
    )
    query_sha256 = hashlib.sha256(statement.encode("utf-8")).hexdigest()
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("Content-Type", ""))
                body = response.read(maximum_response_bytes + 1)
            if status != 200:
                raise SkyServerSQLError(
                    f"SkyServer returned HTTP {status}"
                )
            if len(body) > maximum_response_bytes:
                raise SkyServerSQLError(
                    "SkyServer response exceeded the byte limit"
                )
            frame = _parse_csv(body, content_type)
            if len(frame) > maximum_rows:
                raise SkyServerSQLError(
                    "SkyServer response exceeded the configured row bound"
                )
            receipt = SkyServerSQLReceipt(
                endpoint=root,
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                content_type=content_type,
                response_sha256=hashlib.sha256(body).hexdigest(),
                query_sha256=query_sha256,
                maximum_rows=maximum_rows,
            )
            return frame, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise SkyServerSQLError(
                    f"SkyServer returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise SkyServerSQLError(
                    f"SkyServer transport failed: {type(error).__name__}"
                ) from error
        except SkyServerSQLError:
            raise
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise SkyServerSQLError(str(last_error))
