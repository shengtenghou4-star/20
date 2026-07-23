from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from astropy.table import Table
import pytest

from hou_compact.lamost_conesearch import LamostConeSearchError, query_lamost_cone


@dataclass
class _Response:
    body: bytes
    content_type: str = "application/x-votable+xml"
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


def _votable_bytes() -> bytes:
    table = Table(
        {
            "gaia_source_id": ["1234567890123456789"],
            "obsid": [10],
            "mjd": [59000],
            "rv": [12.5],
            "rv_err": [1.2],
        }
    )
    buffer = BytesIO()
    table.write(buffer, format="votable")
    return buffer.getvalue()


def test_conesearch_parses_votable_and_redacts_position_from_receipt() -> None:
    seen_url = ""

    def opener(request: object, *, timeout: float) -> _Response:
        nonlocal seen_url
        assert timeout == 12.0
        seen_url = str(getattr(request, "full_url"))
        return _Response(_votable_bytes())

    frame, receipt = query_lamost_cone(
        "https://example.test/conesearch",
        ra_deg=10.0004738,
        dec_deg=40.9952444,
        radius_deg=0.001,
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    assert len(frame) == 1
    assert set(frame.columns) == {"gaia_source_id", "obsid", "mjd", "rv", "rv_err"}
    assert "ra=10.000473800000" in seen_url
    record = receipt.to_record()
    assert record["endpoint"] == "https://example.test/conesearch"
    assert "10.0004738" not in str(record)
    assert "40.9952444" not in str(record)
    assert "1234567890123456789" not in str(record)


def test_conesearch_rejects_html() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b"<!doctype html><html>login</html>", "text/html")

    with pytest.raises(LamostConeSearchError, match="HTML"):
        query_lamost_cone(
            "https://example.test/conesearch",
            ra_deg=1.0,
            dec_deg=2.0,
            radius_deg=0.001,
            retries=0,
            opener=opener,
        )


def test_conesearch_rejects_invalid_radius() -> None:
    with pytest.raises(ValueError, match="radius_deg"):
        query_lamost_cone(
            "https://example.test/conesearch",
            ra_deg=1.0,
            dec_deg=2.0,
            radius_deg=0.0,
        )
