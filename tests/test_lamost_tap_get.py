from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from hou_compact.lamost_tap_get import (
    LamostTapGetError,
    TapGetService,
    tap_sync_get,
)


@dataclass
class _Response:
    body: bytes
    content_type: str = "text/csv"
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


def test_tap_sync_get_parses_csv_and_redacts_query_from_receipt() -> None:
    seen_urls: list[str] = []

    def opener(request: object, *, timeout: float) -> _Response:
        assert timeout == 12.0
        seen_urls.append(str(getattr(request, "full_url")))
        return _Response(b"obsid,rv,rv_err\n10,12.5,0.3\n")

    query = "SELECT obsid, rv, rv_err FROM dr8.test WHERE obsid IN (10)"
    frame, receipt = tap_sync_get(
        "https://example.test/tap",
        query,
        maxrec=5,
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    assert frame.to_dict(orient="records") == [
        {"obsid": 10, "rv": 12.5, "rv_err": 0.3}
    ]
    assert len(seen_urls) == 1
    assert "REQUEST=doQuery" in seen_urls[0]
    assert "QUERY=" in seen_urls[0]
    assert receipt.endpoint == "https://example.test/tap/sync"
    assert "SELECT" not in str(receipt.to_record())
    assert receipt.response_bytes > 0


def test_tap_sync_get_rejects_html_error_page() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b"<!doctype html><html>error</html>", "text/html")

    with pytest.raises(LamostTapGetError, match="HTML"):
        tap_sync_get(
            "https://example.test/tap",
            "SELECT 1",
            maxrec=1,
            retries=0,
            opener=opener,
        )


def test_tap_sync_get_enforces_response_byte_limit() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b"x" * 2_000)

    with pytest.raises(LamostTapGetError, match="byte limit"):
        tap_sync_get(
            "https://example.test/tap",
            "SELECT 1",
            maxrec=1,
            retries=0,
            maximum_response_bytes=1_024,
            opener=opener,
        )


def test_service_adapter_accumulates_candidate_safe_receipts(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = pd.DataFrame({"table_name": ["dr8.test"], "column_name": ["obsid"]})

    def fake_get(
        tap_url: str,
        query: str,
        *,
        maxrec: int,
        timeout: float,
        retries: int,
        maximum_response_bytes: int,
    ) -> tuple[pd.DataFrame, object]:
        del tap_url, query, maxrec, timeout, retries, maximum_response_bytes
        from hou_compact.lamost_tap_get import TapGetReceipt

        return expected, TapGetReceipt(
            endpoint="https://example.test/tap/sync",
            status=200,
            attempts=1,
            response_bytes=20,
            content_type="text/csv",
            sha256="a" * 64,
            query_sha256="b" * 64,
            maxrec=10,
        )

    monkeypatch.setattr("hou_compact.lamost_tap_get.tap_sync_get", fake_get)
    service = TapGetService("https://example.test/tap")
    result = service.run_sync("SELECT table_name, column_name", maxrec=10)
    pd.testing.assert_frame_equal(result, expected)
    assert len(service.receipts) == 1
    assert service.receipts[0].query_sha256 == "b" * 64
