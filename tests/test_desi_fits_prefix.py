from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from astropy.io import fits
import numpy as np

from hou_compact.desi_fits_prefix import fetch_fits_prefix, parse_rvtab_prefix


@dataclass
class _Response:
    body: bytes
    status: int = 206

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/fits",
            "Content-Range": f"bytes 0-{len(self.body) - 1}/999999",
        }

    def read(self, size: int) -> bytes:
        return self.body[:size]

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _fits_bytes() -> bytes:
    rvtab = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="TARGETID", format="K", array=np.array([101, 102])),
            fits.Column(name="EXPID", format="K", array=np.array([1, 2])),
            fits.Column(name="VRAD", format="D", array=np.array([12.0, 13.0])),
            fits.Column(name="VRAD_ERR", format="D", array=np.array([0.2, 0.3])),
            fits.Column(name="RVS_WARN", format="K", array=np.array([0, 0])),
            fits.Column(name="SUCCESS", format="L", array=np.array([True, True])),
        ],
        name="RVTAB",
    )
    buffer = BytesIO()
    fits.HDUList([fits.PrimaryHDU(), rvtab]).writeto(buffer)
    return buffer.getvalue()


def test_fetch_and_parse_rvtab_prefix() -> None:
    full = _fits_bytes()

    def opener(request: object, *, timeout: float) -> _Response:
        assert timeout == 12.0
        assert "Range" in dict(getattr(request, "headers"))
        return _Response(full)

    prefix, receipt = fetch_fits_prefix(
        "https://example.test/rvtab.fits",
        prefix_bytes=16 * 1024,
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    assert receipt.status == 206
    assert receipt.content_range_present
    contract = parse_rvtab_prefix(prefix)
    assert contract["extname"] == "RVTAB"
    assert contract["row_count"] == 2
    assert contract["columns"] == (
        "TARGETID",
        "EXPID",
        "VRAD",
        "VRAD_ERR",
        "RVS_WARN",
        "SUCCESS",
    )
