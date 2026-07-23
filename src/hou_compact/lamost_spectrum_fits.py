"""Bounded public LAMOST FITS retrieval and LASP RV extraction.

The public ConeSearch catalogue supplies exact Gaia DR3 identity and a spectrum
``obsid``.  This module retrieves the corresponding low-resolution FITS product
from the documented OpenAPI spectrum endpoint and reads the LASP radial velocity
and uncertainty from FITS headers.  Source values remain private research data;
public receipts contain only response hashes and schema-level key names.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import hashlib
import math
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from astropy.io import fits


class LamostSpectrumFITSError(RuntimeError):
    """Raised when a public LAMOST FITS product violates the frozen contract."""


@dataclass(frozen=True)
class SpectrumFITSReceipt:
    endpoint: str
    status: int
    attempts: int
    response_bytes: int
    content_type: str
    sha256: str
    hdu_count: int
    header_keys: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return asdict(self)


_RV_ALIASES = (
    "RV",
    "RV_LASP",
    "LASP_RV",
    "VRAD",
    "RADVEL",
)
_RV_ERROR_ALIASES = (
    "RV_ERR",
    "RVERR",
    "RV_LASP_ERR",
    "LASP_RV_ERR",
    "VRAD_ERR",
    "RADVEL_ERR",
)


def _finite_header_value(headers: list[fits.Header], aliases: tuple[str, ...]) -> float | None:
    for header in headers:
        for alias in aliases:
            if alias not in header:
                continue
            try:
                value = float(header[alias])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                return value
    return None


def download_lamost_spectrum_fits(
    openapi_root: str,
    *,
    dr_version: str,
    sub_version: str,
    obsid: int,
    resolution: str = "lrs",
    timeout: float = 180.0,
    retries: int = 2,
    maximum_response_bytes: int = 64 * 1024 * 1024,
    opener: Any = urlopen,
) -> tuple[bytes, SpectrumFITSReceipt]:
    """Download one bounded public spectrum FITS product by exact obsid."""

    root = openapi_root.rstrip("/")
    if not root.startswith("https://"):
        raise ValueError("openapi_root must use HTTPS")
    if not isinstance(obsid, int) or obsid < 0:
        raise ValueError("obsid must be a non-negative integer")
    if resolution not in {"lrs", "mrs"}:
        raise ValueError("resolution must be 'lrs' or 'mrs'")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 2880:
        raise ValueError("maximum_response_bytes must be at least one FITS block")

    endpoint = (
        f"{root}/{dr_version}/{sub_version}/{resolution}/spectrum/fits"
    )
    url = f"{endpoint}?{urlencode({'obsid': obsid})}"
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded LAMOST FITS client",
            "Accept": "application/fits,application/octet-stream,*/*;q=0.1",
        },
    )
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("Content-Type", ""))
                body = response.read(maximum_response_bytes + 1)
            if len(body) > maximum_response_bytes:
                raise LamostSpectrumFITSError("spectrum FITS exceeded the byte limit")
            if status != 200:
                raise LamostSpectrumFITSError(
                    f"spectrum FITS returned HTTP {status}"
                )
            preview = body[:8192].lstrip().lower()
            if preview.startswith(b"<!doctype html") or b"<html" in preview:
                raise LamostSpectrumFITSError(
                    "spectrum FITS returned HTML instead of FITS"
                )
            if body[:6] != b"SIMPLE":
                raise LamostSpectrumFITSError(
                    "spectrum endpoint did not return a FITS primary header"
                )
            try:
                with fits.open(
                    BytesIO(body),
                    memmap=False,
                    lazy_load_hdus=False,
                    ignore_missing_simple=False,
                ) as hdul:
                    headers = [hdu.header.copy() for hdu in hdul]
            except Exception as error:
                raise LamostSpectrumFITSError(
                    f"spectrum response was not readable FITS: {type(error).__name__}"
                ) from error
            header_keys = tuple(
                sorted(
                    {
                        str(key).strip().upper()
                        for header in headers
                        for key in header.keys()
                        if str(key).strip()
                    }
                )
            )
            receipt = SpectrumFITSReceipt(
                endpoint=endpoint,
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                content_type=content_type,
                sha256=hashlib.sha256(body).hexdigest(),
                hdu_count=len(headers),
                header_keys=header_keys,
            )
            return body, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise LamostSpectrumFITSError(
                    f"spectrum FITS returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise LamostSpectrumFITSError(
                    f"spectrum FITS transport failed: {type(error).__name__}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise LamostSpectrumFITSError(str(last_error))


def extract_lasp_rv_from_fits(body: bytes) -> dict[str, float]:
    """Extract finite LASP RV and positive uncertainty from FITS headers."""

    try:
        with fits.open(
            BytesIO(body),
            memmap=False,
            lazy_load_hdus=False,
            ignore_missing_simple=False,
        ) as hdul:
            headers = [hdu.header for hdu in hdul]
            rv = _finite_header_value(headers, _RV_ALIASES)
            rv_error = _finite_header_value(headers, _RV_ERROR_ALIASES)
    except Exception as error:
        raise LamostSpectrumFITSError(
            f"unable to inspect spectrum FITS headers: {type(error).__name__}"
        ) from error
    if rv is None:
        raise LamostSpectrumFITSError("spectrum FITS contains no finite LASP RV header")
    if rv_error is None or rv_error <= 0:
        raise LamostSpectrumFITSError(
            "spectrum FITS contains no finite positive LASP RV uncertainty header"
        )
    return {"rv": rv, "rv_err": rv_error}
