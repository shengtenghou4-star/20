"""Bounded anonymous IVOA ConeSearch access for public LAMOST catalogues.

The release website documents an unauthenticated DR8 v2.0 ConeSearch service.
This module treats cone position only as a row-discovery mechanism.  Downstream
Dark-668 matching must still require exact returned Gaia DR3 character equality;
position alone never establishes identity.
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

from astropy.io.votable import parse_single_table
import pandas as pd


class LamostConeSearchError(RuntimeError):
    """Raised when a bounded public ConeSearch response cannot be validated."""


@dataclass(frozen=True)
class ConeSearchReceipt:
    endpoint: str
    status: int
    attempts: int
    response_bytes: int
    content_type: str
    sha256: str
    row_count: int
    column_count: int

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def query_lamost_cone(
    endpoint: str,
    *,
    ra_deg: float,
    dec_deg: float,
    radius_deg: float,
    timeout: float = 120.0,
    retries: int = 2,
    maximum_response_bytes: int = 16 * 1024 * 1024,
    opener: Any = urlopen,
) -> tuple[pd.DataFrame, ConeSearchReceipt]:
    """Query one public LAMOST cone and return a validated table plus safe receipt."""

    base = endpoint.rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("ConeSearch endpoint must use HTTPS")
    for name, value in (
        ("ra_deg", ra_deg),
        ("dec_deg", dec_deg),
        ("radius_deg", radius_deg),
        ("timeout", timeout),
    ):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if not 0 <= ra_deg < 360:
        raise ValueError("ra_deg must lie in [0, 360)")
    if not -90 <= dec_deg <= 90:
        raise ValueError("dec_deg must lie in [-90, 90]")
    if radius_deg <= 0 or radius_deg > 0.5:
        raise ValueError("radius_deg must lie in (0, 0.5]")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 1024:
        raise ValueError("maximum_response_bytes must be at least 1024")

    query = urlencode(
        {
            "ra": f"{ra_deg:.12f}",
            "dec": f"{dec_deg:.12f}",
            "sr": f"{radius_deg:.12g}",
        }
    )
    url = f"{base}?{query}"
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded LAMOST ConeSearch client",
            "Accept": "application/x-votable+xml,text/xml,application/xml;q=0.9,*/*;q=0.1",
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
                raise LamostConeSearchError("ConeSearch response exceeded the byte limit")
            if status != 200:
                raise LamostConeSearchError(f"ConeSearch returned HTTP {status}")
            preview = body[:8192].lstrip().lower()
            if preview.startswith(b"<!doctype html") or b"<html" in preview:
                raise LamostConeSearchError("ConeSearch returned HTML instead of VOTable XML")
            try:
                table = parse_single_table(BytesIO(body)).to_table(use_names_over_ids=True)
                frame = table.to_pandas()
            except Exception as error:
                raise LamostConeSearchError(
                    f"ConeSearch response was not a valid single-table VOTable: {type(error).__name__}"
                ) from error
            frame.columns = [str(column).lower() for column in frame.columns]
            receipt = ConeSearchReceipt(
                endpoint=base,
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                content_type=content_type,
                sha256=hashlib.sha256(body).hexdigest(),
                row_count=len(frame),
                column_count=len(frame.columns),
            )
            return frame, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise LamostConeSearchError(
                    f"ConeSearch returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise LamostConeSearchError(
                    f"ConeSearch transport failed: {type(error).__name__}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise LamostConeSearchError(str(last_error))
