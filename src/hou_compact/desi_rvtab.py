"""Bounded public DESI single-epoch RVTAB retrieval and schema inspection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import hashlib
import math
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from astropy.io import fits


class DesiRVTabError(RuntimeError):
    """Raised when a DESI single-epoch FITS product violates the contract."""


@dataclass(frozen=True)
class DesiRVTabReceipt:
    status: int
    attempts: int
    response_bytes: int
    content_type: str
    sha256: str
    hdu_count: int
    hdu_names: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def download_rvtab_fits(
    url: str,
    *,
    timeout: float = 300.0,
    retries: int = 2,
    maximum_response_bytes: int = 256 * 1024 * 1024,
    opener: Any = urlopen,
) -> tuple[bytes, DesiRVTabReceipt]:
    """Download one bounded HTTPS DESI RVTAB FITS file."""

    if not url.startswith("https://"):
        raise ValueError("DESI RVTAB URL must use HTTPS")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 2880:
        raise ValueError("maximum_response_bytes must be at least one FITS block")

    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded DESI RVTAB client",
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
            if status != 200:
                raise DesiRVTabError(f"DESI RVTAB returned HTTP {status}")
            if len(body) > maximum_response_bytes:
                raise DesiRVTabError("DESI RVTAB exceeded the byte limit")
            if body[:6] != b"SIMPLE":
                raise DesiRVTabError("DESI RVTAB did not return a FITS primary header")
            try:
                with fits.open(
                    BytesIO(body),
                    memmap=False,
                    lazy_load_hdus=False,
                    ignore_missing_simple=False,
                ) as hdul:
                    names = tuple(str(hdu.name or "PRIMARY").upper() for hdu in hdul)
                    count = len(hdul)
            except Exception as error:
                raise DesiRVTabError(
                    f"DESI RVTAB was not readable FITS: {type(error).__name__}"
                ) from error
            receipt = DesiRVTabReceipt(
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                content_type=content_type,
                sha256=hashlib.sha256(body).hexdigest(),
                hdu_count=count,
                hdu_names=names,
            )
            return body, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise DesiRVTabError(
                    f"DESI RVTAB returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise DesiRVTabError(
                    f"DESI RVTAB transport failed: {type(error).__name__}"
                ) from error
        except DesiRVTabError:
            raise
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise DesiRVTabError(str(last_error))


def inspect_rvtab_schema(body: bytes) -> dict[str, tuple[str, ...]]:
    """Return HDU column names only; no row values are exposed."""

    try:
        with fits.open(
            BytesIO(body),
            memmap=False,
            lazy_load_hdus=False,
            ignore_missing_simple=False,
        ) as hdul:
            result: dict[str, tuple[str, ...]] = {}
            for index, hdu in enumerate(hdul):
                name = str(hdu.name or f"HDU{index}").upper()
                columns = getattr(hdu, "columns", None)
                result[name] = tuple(str(value).upper() for value in (columns.names or [])) if columns is not None else ()
            return result
    except Exception as error:
        raise DesiRVTabError(
            f"unable to inspect DESI RVTAB schema: {type(error).__name__}"
        ) from error


def count_target_rows(body: bytes, targetid: int) -> tuple[str, int]:
    """Find the table HDU containing TARGETID and count one sample target in memory."""

    if not isinstance(targetid, int):
        raise ValueError("targetid must be an integer")
    try:
        with fits.open(
            BytesIO(body),
            memmap=False,
            lazy_load_hdus=False,
            ignore_missing_simple=False,
        ) as hdul:
            candidates: list[tuple[str, int]] = []
            for index, hdu in enumerate(hdul):
                columns = getattr(hdu, "columns", None)
                names = [str(value).upper() for value in (columns.names or [])] if columns is not None else []
                if "TARGETID" not in names or hdu.data is None:
                    continue
                count = int((hdu.data["TARGETID"] == targetid).sum())
                candidates.append((str(hdu.name or f"HDU{index}").upper(), count))
            positive = [item for item in candidates if item[1] > 0]
            if len(positive) != 1:
                raise DesiRVTabError(
                    "expected one TARGETID-bearing HDU with the sample target; "
                    f"found {len(positive)}"
                )
            return positive[0]
    except DesiRVTabError:
        raise
    except Exception as error:
        raise DesiRVTabError(
            f"unable to count sample TARGETID rows: {type(error).__name__}"
        ) from error
