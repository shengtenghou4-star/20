from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from astropy.io import fits
import pytest

from hou_compact.lamost_spectrum_fits import (
    LamostSpectrumFITSError,
    download_lamost_spectrum_fits,
    extract_lasp_rv_from_fits,
)


@dataclass
class _Response:
    body: bytes
    content_type: str = "application/fits"
    status: int = 200

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Type": self.content_type}

    def read(self, _: int) -> bytes:
        return self.body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _fits_bytes(*, rv: float = 32.5, rv_err: float = 1.2) -> bytes:
    primary = fits.PrimaryHDU()
    extension = fits.ImageHDU()
    extension.header["RV"] = rv
    extension.header["RV_ERR"] = rv_err
    buffer = BytesIO()
    fits.HDUList([primary, extension]).writeto(buffer)
    return buffer.getvalue()


def test_download_validates_fits_and_redacts_obsid_from_receipt() -> None:
    seen_url = ""

    def opener(request: object, *, timeout: float) -> _Response:
        nonlocal seen_url
        assert timeout == 12.0
        seen_url = str(getattr(request, "full_url"))
        return _Response(_fits_bytes())

    body, receipt = download_lamost_spectrum_fits(
        "https://example.test/openapi",
        dr_version="dr8",
        sub_version="v2.0",
        obsid=403143,
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    assert "obsid=403143" in seen_url
    assert body.startswith(b"SIMPLE")
    record = receipt.to_record()
    assert record["endpoint"].endswith("/dr8/v2.0/lrs/spectrum/fits")
    assert "403143" not in str(record)
    assert record["hdu_count"] == 2
    assert "RV" in record["header_keys"]
    assert "RV_ERR" in record["header_keys"]


def test_extract_lasp_rv_reads_extension_header() -> None:
    result = extract_lasp_rv_from_fits(_fits_bytes(rv=-18.75, rv_err=0.85))
    assert result == {"rv": -18.75, "rv_err": 0.85}


def test_extract_lasp_rv_rejects_missing_uncertainty() -> None:
    primary = fits.PrimaryHDU()
    primary.header["RV"] = 12.0
    buffer = BytesIO()
    primary.writeto(buffer)
    with pytest.raises(LamostSpectrumFITSError, match="uncertainty"):
        extract_lasp_rv_from_fits(buffer.getvalue())


def test_download_rejects_json_error_envelope() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b'{"error":"token required"}', "application/json")

    with pytest.raises(LamostSpectrumFITSError, match="FITS primary"):
        download_lamost_spectrum_fits(
            "https://example.test/openapi",
            dr_version="dr8",
            sub_version="v2.0",
            obsid=403143,
            retries=0,
            opener=opener,
        )
