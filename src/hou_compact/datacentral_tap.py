"""Bounded anonymous TAP transport for Data Central catalogue queries.

Receipts deliberately omit ADQL text and row values.  They retain only the
public service endpoint, status, byte counts, response and query hashes, and
the configured row bound.  Source-level queries must still be encrypted before
persistence by their caller.
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

from astropy.table import Table
import pandas as pd


class DataCentralTapError(RuntimeError):
    """Raised when a bounded Data Central TAP response violates the contract."""


@dataclass(frozen=True)
class DataCentralTapReceipt:
    endpoint: str
    status: int
    attempts: int
    response_bytes: int
    content_type: str
    response_sha256: str
    query_sha256: str
    maxrec: int

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _parse_table(body: bytes, content_type: str) -> pd.DataFrame:
    if not body:
        raise DataCentralTapError("Data Central TAP returned an empty response")
    preview = body[:8192].lower()
    if b'query_status" value="error' in preview or b"query_status' value='error" in preview:
        raise DataCentralTapError("Data Central TAP VOTable reported QUERY_STATUS=ERROR")
    if b"<html" in preview or b"<!doctype html" in preview:
        raise DataCentralTapError("Data Central TAP returned HTML instead of table data")
    is_xml = (
        "xml" in content_type.lower()
        or body.lstrip().startswith(b"<?xml")
        or b"<votable" in preview
    )
    try:
        if is_xml:
            return Table.read(BytesIO(body), format="votable").to_pandas()
        return pd.read_csv(BytesIO(body), dtype="string")
    except Exception as error:
        raise DataCentralTapError(
            "Data Central TAP response could not be parsed as CSV/VOTable: "
            f"{type(error).__name__}"
        ) from error


def tap_sync_get(
    tap_root: str,
    query: str,
    *,
    maxrec: int,
    timeout: float = 180.0,
    retries: int = 2,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    maximum_url_characters: int = 16_000,
    opener: Any = urlopen,
) -> tuple[pd.DataFrame, DataCentralTapReceipt]:
    """Execute one bounded anonymous TAP sync query using HTTPS GET."""

    root = tap_root.rstrip("/")
    if not root.startswith("https://"):
        raise ValueError("tap_root must use HTTPS")
    statement = query.strip()
    if not statement:
        raise ValueError("query must not be empty")
    if maxrec < 1:
        raise ValueError("maxrec must be positive")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 1024:
        raise ValueError("maximum_response_bytes must be at least 1024")
    if maximum_url_characters < 1024:
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
        raise DataCentralTapError("encoded TAP query exceeds the URL-length limit")
    request = Request(
        request_url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded Data Central TAP client",
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
                raise DataCentralTapError(
                    f"Data Central TAP returned HTTP {status}"
                )
            if len(body) > maximum_response_bytes:
                raise DataCentralTapError(
                    "Data Central TAP response exceeded the byte limit"
                )
            frame = _parse_table(body, content_type)
            receipt = DataCentralTapReceipt(
                endpoint=endpoint,
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                content_type=content_type,
                response_sha256=hashlib.sha256(body).hexdigest(),
                query_sha256=query_sha256,
                maxrec=maxrec,
            )
            return frame, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise DataCentralTapError(
                    f"Data Central TAP returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise DataCentralTapError(
                    "Data Central TAP transport failed: "
                    f"{type(error).__name__}"
                ) from error
        except DataCentralTapError:
            raise
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise DataCentralTapError(str(last_error))
