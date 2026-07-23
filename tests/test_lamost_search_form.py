from __future__ import annotations

from dataclasses import dataclass

import pytest

from hou_compact.lamost_search_form import (
    encode_multipart_fields,
    submit_search_form,
)


@dataclass
class _Response:
    body: bytes
    url: str
    content_type: str = "text/html"
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


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.request: object | None = None
        self.timeout: float | None = None

    def open(self, request: object, *, timeout: float) -> _Response:
        self.request = request
        self.timeout = timeout
        return self.response


def test_multipart_encoder_preserves_repeated_fields() -> None:
    body = encode_multipart_fields(
        [
            ("output.combined.obsid", "on"),
            ("output.combined.rv", "on"),
            ("output.combined.rv", "second"),
        ],
        boundary="HouCompactBoundary123",
    )
    text = body.decode("utf-8")
    assert text.count('name="output.combined.rv"') == 2
    assert text.startswith("--HouCompactBoundary123\r\n")
    assert text.endswith("--HouCompactBoundary123--\r\n")


def test_search_form_receipt_redacts_field_values_and_final_query() -> None:
    response = _Response(
        b"<!doctype html><html><body>results</body></html>",
        "https://www.lamost.org/dr8/v2.0/result?query_id=secret-7",
    )
    opener = _Opener(response)
    fields = [
        ("pos.radecTextarea", "10.0004738,40.9952444,2.0"),
        ("obsidTextarea", "195309107"),
        ("output.combined.rv", "rv"),
    ]
    body, final_url, receipt = submit_search_form(
        "https://www.lamost.org/dr8/v2.0/q",
        fields,
        timeout=12.0,
        retries=0,
        boundary="HouCompactBoundary123",
        opener=opener,
    )
    assert body.startswith(b"<!doctype html>")
    assert final_url.endswith("query_id=secret-7")
    assert opener.timeout == 12.0
    request = opener.request
    assert request is not None
    assert getattr(request, "method") == "POST"
    assert b"195309107" in bytes(getattr(request, "data"))
    record = receipt.to_record()
    assert record["final_path"] == "/dr8/v2.0/result"
    assert record["response_kind"] == "html"
    assert "secret-7" not in str(record)
    assert "195309107" not in str(record)
    assert "10.0004738" not in str(record)


def test_search_form_detects_csv_response() -> None:
    opener = _Opener(
        _Response(
            b"obsid,rv,rv_err\n10,2.5,0.4\n",
            "https://www.lamost.org/dr8/v2.0/q",
            content_type="text/csv",
        )
    )
    body, _, receipt = submit_search_form(
        "https://www.lamost.org/dr8/v2.0/q",
        [("output.fmt", "csv")],
        retries=0,
        boundary="HouCompactBoundary123",
        opener=opener,
    )
    assert body.startswith(b"obsid,rv")
    assert receipt.response_kind == "csv"


def test_multipart_rejects_header_injection() -> None:
    with pytest.raises(ValueError, match="field name"):
        encode_multipart_fields(
            [("bad\r\nname", "value")],
            boundary="HouCompactBoundary123",
        )
