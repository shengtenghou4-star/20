from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from astropy.io import fits
import numpy as np
import pytest

from hou_compact.desi_rvtab import (
    DesiRVTabError,
    count_target_rows,
    download_rvtab_fits,
    inspect_rvtab_schema,
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


def _fits_bytes() -> bytes:
    rvtab = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="TARGETID", format="K", array=np.array([101, 102])),
            fits.Column(name="EXPID", format="K", array=np.array([1, 2])),
            fits.Column(name="VRAD", format="D", array=np.array([12.0, 13.0])),
            fits.Column(name="VRAD_ERR", format="D", array=np.array([0.2, 0.3])),
        ],
        name="RVTAB",
    )
    fibermap = fits.BinTableHDU.from_columns(
        [fits.Column(name="TARGETID", format="K", array=np.array([201, 202]))],
        name="FIBERMAP",
    )
    buffer = BytesIO()
    fits.HDUList([fits.PrimaryHDU(), rvtab, fibermap]).writeto(buffer)
    return buffer.getvalue()


def test_download_and_inspect_schema() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request
        assert timeout == 12.0
        return _Response(_fits_bytes())

    body, receipt = download_rvtab_fits(
        "https://example.test/rvtab.fits",
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    assert receipt.hdu_names == ("PRIMARY", "RVTAB", "FIBERMAP")
    schema = inspect_rvtab_schema(body)
    assert {"TARGETID", "EXPID", "VRAD", "VRAD_ERR"}.issubset(schema["RVTAB"])
    hdu_name, count = count_target_rows(body, 101)
    assert hdu_name == "RVTAB"
    assert count == 1


def test_download_rejects_html() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b"<html>not fits</html>", "text/html")

    with pytest.raises(DesiRVTabError, match="FITS primary"):
        download_rvtab_fits(
            "https://example.test/rvtab.fits",
            retries=0,
            opener=opener,
        )
