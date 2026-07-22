"""Bounded GET transport for the first-party LAMOST TAP sync endpoint.

LAMOST publishes an IVOA TAP URL, but its sync endpoint rejects the POST request
used by PyVO in the current public deployment. The query sizes used by Dark-668 are
small and exact, so this module provides a bounded GET adapter without logging query
text or source identifiers. Receipts retain only endpoint, size, status, and hashes.
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
from astropy.table import Table


class LamostTapGetError(RuntimeError):
    """Raised when a bounded LAMOST TAP GET query cannot be validated."""


@dataclass(frozen=True)
class TapGetReceipt:
    endpoint: str
    status: int
    attempts: int
    response_bytes: int
    content_type: str
    sha256: str
    query_sha256: str
    maxrec: int

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _parse_tap_body(body: bytes, content_type: str) -> pd.DataFrame:
    if not body:
        raise LamostTapGetError("LAMOST TAP returned an empty response")
    preview = body[:8_192].lower()
    if b'query_status" value="error' in preview or b"query_status' value='error" in preview:
        raise LamostTapGetError("LAMOST TAP VOTable reported QUERY_STATUS=ERROR")
    if b"<html" in preview or b"<!doctype html" in preview:
        raise LamostTapGetError("LAMOST TAP returned HTML instead of table data")

    normalized_type = content_type.lower()
    is_xml = (
        "xml" in normalized_type
        or body.lstrip().startswith(b"<?xml")
        or b"<votable" in preview
    )
    try:
        if is_xml:
            return Table.read(BytesIO(body), format="votable").to_pandas()
        return pd.read_csv(BytesIO(body))
    except Exception as error:
        raise LamostTapGetError(
            f"LAMOST TAP response could not be parsed as CSV/VOTable: {type(error).__name__}"
        ) from error


def tap_sync_get(
    tap_url: str,
    query: str,
    *,
    maxrec: int,
    timeout: float = 180.0,
    retries: int = 2,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    maximum_url_characters: int = 16_000,
    opener: Any = urlopen,
) -> tuple[pd.DataFrame, TapGetReceipt]:
    """Execute one TAP sync query over bounded HTTP GET and return a receipt."""

    root = tap_url.rstrip("/")
    if not root.startswith("https://"):
        raise ValueError("tap_url must use HTTPS")
    statement = query.strip()
    if not statement:
        raise ValueError("query must not be empty")
    if maxrec < 1:
        raise ValueError("maxrec must be positive")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 1_024:
        raise ValueError("maximum_response_bytes must be at least 1024")
    if maximum_url_characters < 1_024:
        raise ValueError("maximum_url_characters must be at least 1024")

    endpoint = f"{root}/sync"
    encoded = urlencode(
        {
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": "csv",
            "MAXREC": str(maxrec),
            "QUERY": statement,
        }
    )
    request_url = f"{endpoint}?{encoded}"
    if len(request_url) > maximum_url_characters:
        raise LamostTapGetError(
            "encoded TAP GET query exceeds the configured URL-length limit"
        )
    request = Request(
        request_url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded LAMOST TAP GET client",
            "Accept": "text/csv,application/x-votable+xml,application/xml;q=0.8,*/*;q=0.1",
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
                raise LamostTapGetError(f"LAMOST TAP GET returned HTTP {status}")
            if len(body) > maximum_response_bytes:
                raise LamostTapGetError("LAMOST TAP response exceeded the byte limit")
            frame = _parse_tap_body(body, content_type)
            receipt = TapGetReceipt(
                endpoint=endpoint,
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                content_type=content_type,
                sha256=hashlib.sha256(body).hexdigest(),
                query_sha256=query_sha256,
                maxrec=maxrec,
            )
            return frame, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise LamostTapGetError(
                    f"LAMOST TAP GET returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise LamostTapGetError(
                    f"LAMOST TAP GET transport failed: {type(error).__name__}"
                ) from error
        except LamostTapGetError:
            raise
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise LamostTapGetError(str(last_error))


class TapGetService:
    """Small ``run_sync`` adapter compatible with the Dark-668 TAP query helpers."""

    def __init__(
        self,
        tap_url: str,
        *,
        timeout: float = 180.0,
        retries: int = 2,
        maximum_response_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self.tap_url = tap_url
        self.timeout = timeout
        self.retries = retries
        self.maximum_response_bytes = maximum_response_bytes
        self.receipts: list[TapGetReceipt] = []

    def run_sync(self, query: str, *, maxrec: int) -> pd.DataFrame:
        frame, receipt = tap_sync_get(
            self.tap_url,
            query,
            maxrec=maxrec,
            timeout=self.timeout,
            retries=self.retries,
            maximum_response_bytes=self.maximum_response_bytes,
        )
        self.receipts.append(receipt)
        return frame
