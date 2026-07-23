"""HTTP-range retrieval and FITS header parsing for large DESI RVTAB files."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class FitsPrefixError(RuntimeError):
    """Raised when a bounded FITS prefix cannot establish the header contract."""


@dataclass(frozen=True)
class FitsPrefixReceipt:
    status: int
    attempts: int
    response_bytes: int
    content_type: str
    content_range_present: bool
    sha256: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def fetch_fits_prefix(
    url: str,
    *,
    prefix_bytes: int = 128 * 1024,
    timeout: float = 180.0,
    retries: int = 2,
    opener: Any = urlopen,
) -> tuple[bytes, FitsPrefixReceipt]:
    """Retrieve only an initial byte range from a public HTTPS FITS file."""

    if not url.startswith("https://"):
        raise ValueError("FITS URL must use HTTPS")
    if prefix_bytes < 5760 or prefix_bytes > 2 * 1024 * 1024:
        raise ValueError("prefix_bytes must lie in [5760, 2097152]")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")

    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded FITS header client",
            "Accept": "application/fits,application/octet-stream,*/*;q=0.1",
            "Range": f"bytes=0-{prefix_bytes - 1}",
        },
    )
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("Content-Type", ""))
                content_range = str(response.headers.get("Content-Range", ""))
                body = response.read(prefix_bytes)
            if status not in {200, 206}:
                raise FitsPrefixError(f"FITS range request returned HTTP {status}")
            if len(body) < 5760:
                raise FitsPrefixError("FITS range response is too short")
            if body[:6] != b"SIMPLE":
                raise FitsPrefixError("FITS range response lacks a primary header")
            receipt = FitsPrefixReceipt(
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                content_type=content_type,
                content_range_present=bool(content_range),
                sha256=hashlib.sha256(body).hexdigest(),
            )
            return body, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise FitsPrefixError(
                    f"FITS range request returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise FitsPrefixError(
                    f"FITS range transport failed: {type(error).__name__}"
                ) from error
        except FitsPrefixError:
            raise
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise FitsPrefixError(str(last_error))


def _parse_value(card: str) -> object:
    if len(card) < 10 or card[8] != "=":
        return None
    raw = card[10:].split("/", 1)[0].strip()
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].strip()
    if raw in {"T", "F"}:
        return raw == "T"
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw.replace("D", "E"))
        except ValueError:
            return raw


def parse_header(prefix: bytes, offset: int = 0) -> tuple[dict[str, object], int]:
    """Parse one FITS header and return its block-aligned end offset."""

    values: dict[str, object] = {}
    position = offset
    while position + 80 <= len(prefix):
        try:
            card = prefix[position : position + 80].decode("ascii")
        except UnicodeDecodeError as error:
            raise FitsPrefixError("FITS header contains non-ASCII cards") from error
        keyword = card[:8].strip().upper()
        if keyword == "END":
            used = position + 80 - offset
            padded = ((used + 2879) // 2880) * 2880
            return values, offset + padded
        if keyword:
            values[keyword] = _parse_value(card)
        position += 80
    raise FitsPrefixError("FITS prefix ended before the END header card")


def parse_rvtab_prefix(prefix: bytes) -> dict[str, object]:
    """Parse the primary and first extension header from a DESI RVTAB prefix."""

    primary, primary_end = parse_header(prefix, 0)
    if int(primary.get("NAXIS", 0) or 0) != 0:
        raise FitsPrefixError("expected an empty DESI FITS primary HDU")
    extension, _ = parse_header(prefix, primary_end)
    extname = str(extension.get("EXTNAME", "")).strip().upper()
    if extname != "RVTAB":
        raise FitsPrefixError(f"expected first extension RVTAB, found {extname or 'none'}")
    fields = int(extension.get("TFIELDS", 0) or 0)
    if fields < 1 or fields > 1000:
        raise FitsPrefixError("invalid RVTAB TFIELDS count")
    columns: list[str] = []
    for index in range(1, fields + 1):
        value = extension.get(f"TTYPE{index}")
        if value is None:
            continue
        name = str(value).strip().upper()
        if re.fullmatch(r"[A-Z0-9_]+", name) is None:
            raise FitsPrefixError("unsafe RVTAB column name")
        columns.append(name)
    if len(columns) != fields:
        raise FitsPrefixError("RVTAB header is missing TTYPE cards")
    return {
        "extname": extname,
        "row_bytes": int(extension.get("NAXIS1", 0) or 0),
        "row_count": int(extension.get("NAXIS2", 0) or 0),
        "field_count": fields,
        "columns": tuple(columns),
    }
