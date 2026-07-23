from __future__ import annotations

from dataclasses import dataclass

import pytest

from hou_compact.datacentral_tap import DataCentralTapError, tap_sync_get


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
    seen_url = ""

    def opener(request: object, *, timeout: float) -> _Response:
        nonlocal seen_url
        assert timeout == 12.0
        seen_url = str(getattr(request, "full_url"))
        return _Response(b"table_name\ngalah_dr4.allspec\n")

    frame, receipt = tap_sync_get(
        "https://example.test/vo/tap",
        "SELECT table_name FROM TAP_SCHEMA.tables",
        maxrec=10,
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    assert frame["table_name"].tolist() == ["galah_dr4.allspec"]
    assert "QUERY=" in seen_url
    record = receipt.to_record()
    assert record["endpoint"] == "https://example.test/vo/tap/sync"
    assert "SELECT" not in str(record)
    assert len(record["query_sha256"]) == 64


def test_tap_sync_get_rejects_html() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b"<!doctype html><html>nope</html>", "text/html")

    with pytest.raises(DataCentralTapError, match="HTML"):
        tap_sync_get(
            "https://example.test/vo/tap",
            "SELECT TOP 1 * FROM example",
            maxrec=1,
            retries=0,
            opener=opener,
        )
