from __future__ import annotations

from dataclasses import dataclass

import pytest

from hou_compact.skyserver_sql import SkyServerSQLError, skyserver_sql_get


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


def test_skyserver_sql_get_parses_csv_and_redacts_query() -> None:
    seen_url = ""

    def opener(request: object, *, timeout: float) -> _Response:
        nonlocal seen_url
        assert timeout == 12.0
        seen_url = str(getattr(request, "full_url"))
        return _Response(b"TABLE_NAME,COLUMN_NAME\napogeeVisit,VHELIO\n")

    frame, receipt = skyserver_sql_get(
        "https://example.test/SqlSearch",
        "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS",
        maximum_rows=10,
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    assert frame.iloc[0]["TABLE_NAME"] == "apogeeVisit"
    assert "cmd=" in seen_url
    record = receipt.to_record()
    assert record["endpoint"] == "https://example.test/SqlSearch"
    assert "SELECT" not in str(record)
    assert len(record["query_sha256"]) == 64


def test_skyserver_sql_get_rejects_html() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b"<!doctype html><html>error</html>", "text/html")

    with pytest.raises(SkyServerSQLError, match="HTML"):
        skyserver_sql_get(
            "https://example.test/SqlSearch",
            "SELECT TOP 1 * FROM apogeeVisit",
            maximum_rows=1,
            retries=0,
            opener=opener,
        )
