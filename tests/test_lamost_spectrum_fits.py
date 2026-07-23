from __future__ import annotations

from dataclasses import dataclass
import gzip
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
    assert record["response_kind"] == "fits"
    assert record["decoded_bytes"] == len(body)
    assert record["hdu_count"] == 2
    assert "RV" in record["header_keys"]
    assert "RV_ERR" in record["header_keys"]


def test_download_decodes_bounded_gzip_fits() -> None:
    decoded = _fits_bytes(rv=44.0, rv_err=0.7)
    encoded = gzip.compress(decoded)

    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(encoded, "application/fits")

    body, receipt = download_lamost_spectrum_fits(
        "https://example.test/openapi",
        dr_version="dr8",
        sub_version="v2.0",
        obsid=403143,
        retries=0,
        opener=opener,
    )
    assert body == decoded
    assert receipt.response_kind == "gzip_fits"
    assert receipt.response_bytes == len(encoded)
    assert receipt.decoded_bytes == len(decoded)
    assert extract_lasp_rv_from_fits(body) == {"rv": 44.0, "rv_err": 0.7}


def test_download_rejects_gzip_expansion_over_limit() -> None:
    encoded = gzip.compress(_fits_bytes())

    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(encoded)

    with pytest.raises(LamostSpectrumFITSError, match="decoded spectrum FITS exceeded"):
        download_lamost_spectrum_fits(
            "https://example.test/openapi",
            dr_version="dr8",
            sub_version="v2.0",
            obsid=403143,
            retries=0,
            maximum_decoded_bytes=2880,
            opener=opener,
        )


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


def test_download_rejects_json_error_envelope_with_safe_receipt() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(
            b'{"error":"token required","description":'
            b'"obsid 403143 needs https://example.test/private"}',
            "application/json",
        )

    with pytest.raises(LamostSpectrumFITSError, match="token required") as captured:
        download_lamost_spectrum_fits(
            "https://example.test/openapi",
            dr_version="dr8",
            sub_version="v2.0",
            obsid=403143,
            retries=0,
            opener=opener,
        )
    receipt = captured.value.receipt
    assert receipt is not None
    record = receipt.to_record()
    assert record["response_kind"] == "json_object"
    assert record["diagnostic_error_code"] == "token required"
    assert record["diagnostic_error_description"] == (
        "obsid [number-redacted] needs [url-redacted]"
    )
    assert "403143" not in str(record)
    assert "example.test/private" not in str(record)
