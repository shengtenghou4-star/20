"""Bounded probes for first-party LAMOST catalogue files."""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CatalogueFileError(RuntimeError):
    """Raised when an official catalogue download is not safely usable."""


@dataclass(frozen=True)
class CatalogueFileProbe:
    requested_url: str
    final_url: str
    status: int
    attempts: int
    response_bytes_read: int
    content_type: str
    content_length: str
    content_range: str
    content_disposition: str
    accept_ranges: str
    gzip_magic: bool
    prefix_sha256: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def probe_catalogue_file(
    url: str,
    *,
    timeout: float = 90.0,
    retries: int = 2,
    prefix_bytes: int = 4096,
    opener: Any = urlopen,
) -> CatalogueFileProbe:
    """Read only a small prefix while recording range and size metadata."""

    if not url.startswith("https://"):
        raise ValueError("catalogue file URL must use HTTPS")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if prefix_bytes < 2 or prefix_bytes > 1024 * 1024:
        raise ValueError("prefix_bytes must be between 2 and 1048576")

    request = Request(
        url,
        headers={
            "User-Agent": "HOU-COMPACT/0.1 LAMOST catalogue range probe",
            "Accept": "application/gzip,application/octet-stream,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Range": f"bytes=0-{prefix_bytes - 1}",
        },
    )
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                final_url = str(getattr(response, "geturl", lambda: url)())
                headers = response.headers
                prefix = response.read(prefix_bytes + 1)
            if status not in {200, 206}:
                raise CatalogueFileError(
                    f"catalogue file returned HTTP {status}"
                )
            if len(prefix) > prefix_bytes:
                prefix = prefix[:prefix_bytes]
            content_type = str(headers.get("Content-Type", ""))
            lowered_type = content_type.lower()
            lowered_prefix = prefix[:256].lstrip().lower()
            if "text/html" in lowered_type or lowered_prefix.startswith(b"<!doctype html"):
                raise CatalogueFileError(
                    "catalogue URL returned HTML instead of a data file"
                )
            gzip_magic = prefix.startswith(b"\x1f\x8b")
            if not gzip_magic:
                raise CatalogueFileError(
                    "catalogue response does not begin with gzip magic bytes"
                )
            return CatalogueFileProbe(
                requested_url=url,
                final_url=final_url,
                status=status,
                attempts=attempt + 1,
                response_bytes_read=len(prefix),
                content_type=content_type,
                content_length=str(headers.get("Content-Length", "")),
                content_range=str(headers.get("Content-Range", "")),
                content_disposition=str(headers.get("Content-Disposition", "")),
                accept_ranges=str(headers.get("Accept-Ranges", "")),
                gzip_magic=gzip_magic,
                prefix_sha256=hashlib.sha256(prefix).hexdigest(),
            )
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise CatalogueFileError(
                    f"catalogue file returned HTTP {error.code}"
                ) from error
        except (URLError, OSError, TimeoutError) as error:
            last_error = error
            if attempt >= retries:
                raise CatalogueFileError(
                    "catalogue file transport failed: "
                    f"{type(error).__name__}: {error}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise CatalogueFileError(str(last_error))
