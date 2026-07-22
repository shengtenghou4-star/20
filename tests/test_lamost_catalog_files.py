from __future__ import annotations

from io import BytesIO

import pytest

from hou_compact.lamost_catalog_files import CatalogueFileError, probe_catalogue_file


class FakeHeaders(dict[str, str]):
    pass


class FakeResponse:
    status = 206

    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = body
        self.headers = FakeHeaders(headers)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return BytesIO(self._body).read(size)

    def geturl(self) -> str:
        return "https://example.org/final.csv.gz"


def test_probe_accepts_bounded_gzip_range() -> None:
    body = b"\x1f\x8b" + b"x" * 100

    def opener(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(
            body,
            {
                "Content-Type": "application/gzip",
                "Content-Length": "102",
                "Content-Range": "bytes 0-101/987654",
                "Content-Disposition": 'attachment; filename="catalog.csv.gz"',
                "Accept-Ranges": "bytes",
            },
        )

    result = probe_catalogue_file(
        "https://example.org/catalog.csv.gz",
        prefix_bytes=102,
        opener=opener,
    )
    assert result.status == 206
    assert result.gzip_magic is True
    assert result.content_range.endswith("/987654")
    assert result.final_url == "https://example.org/final.csv.gz"


def test_probe_rejects_login_html() -> None:
    def opener(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(
            b"<!doctype html><title>Sign in</title>",
            {"Content-Type": "text/html"},
        )

    with pytest.raises(CatalogueFileError, match="HTML"):
        probe_catalogue_file(
            "https://example.org/catalog.csv.gz",
            opener=opener,
        )


def test_probe_rejects_non_gzip_payload() -> None:
    def opener(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(
            b"plain text catalogue",
            {"Content-Type": "application/octet-stream"},
        )

    with pytest.raises(CatalogueFileError, match="gzip magic"):
        probe_catalogue_file(
            "https://example.org/catalog.csv.gz",
            opener=opener,
        )
