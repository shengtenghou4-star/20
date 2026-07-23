from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from hou_compact.lamost_openapi_sql import (
    LamostOpenAPISQLError,
    OpenAPISQLService,
    execute_openapi_sql,
)


@dataclass
class _Response:
    body: bytes
    content_type: str = "application/json"
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


def test_openapi_sql_rewrites_schema_query_and_redacts_sql_from_receipt() -> None:
    seen_urls: list[str] = []

    def opener(request: object, *, timeout: float) -> _Response:
        assert timeout == 12.0
        url = str(getattr(request, "full_url"))
        seen_urls.append(url)
        return _Response(
            b'[{"table_name":"mec","column_name":"gaia_source_id",'
            b'"datatype":"bigint"}]'
        )

    query = (
        "SELECT table_name, column_name, datatype FROM TAP_SCHEMA.columns "
        "WHERE column_name IN ('gaia_source_id')"
    )
    frame, receipts = execute_openapi_sql(
        "https://example.test/openapi",
        "dr8",
        "v1.0",
        query,
        maxrec=10,
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    assert frame.to_dict(orient="records") == [
        {
            "table_name": "mec",
            "column_name": "gaia_source_id",
            "datatype": "bigint",
        }
    ]
    assert len(seen_urls) == 1
    parsed = parse_qs(urlparse(seen_urls[0]).query)
    statement = parsed["sql"][0]
    assert "information_schema.columns" in statement
    assert "data_type AS datatype" in statement
    assert "table_schema = 'public'" in statement
    assert statement.endswith("LIMIT 11")
    assert parsed["output.fmt"] == ["json"]
    assert len(receipts) == 1
    record = receipts[0].to_record()
    assert record["endpoint"] == "https://example.test/openapi/dr8/v1.0/sql"
    assert "SELECT" not in str(record)
    assert "gaia_source_id" not in str(record)


def test_openapi_sql_follows_sqlid_result_contract() -> None:
    responses = iter(
        [
            _Response(b'{"sqlid":"job-7"}'),
            _Response(b'{"count":2}'),
            _Response(b'[{"obsid":10,"rv":12.5},{"obsid":11,"rv":13.0}]'),
        ]
    )
    seen_paths: list[str] = []

    def opener(request: object, *, timeout: float) -> _Response:
        del timeout
        seen_paths.append(urlparse(str(getattr(request, "full_url"))).path)
        return next(responses)

    frame, receipts = execute_openapi_sql(
        "https://example.test/openapi",
        "dr8",
        "v1.0",
        "SELECT obsid, rv FROM stellar WHERE obsid IN (10, 11)",
        maxrec=5,
        retries=0,
        opener=opener,
    )
    expected = pd.DataFrame({"obsid": [10, 11], "rv": [12.5, 13.0]})
    pd.testing.assert_frame_equal(frame, expected)
    assert seen_paths == [
        "/openapi/dr8/v1.0/sql",
        "/openapi/dr8/v1.0/get_query_result_count",
        "/openapi/dr8/v1.0/get_query_result",
    ]
    assert [receipt.request_kind for receipt in receipts] == [
        "sql",
        "result_count",
        "result_page",
    ]


def test_service_retains_candidate_safe_failure_receipt_for_html() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b"<!doctype html><html>wrong endpoint</html>", "text/html")

    service = OpenAPISQLService(
        "https://example.test/openapi",
        retries=0,
        opener=opener,
    )
    with pytest.raises(LamostOpenAPISQLError, match="HTML"):
        service.run_sync("SELECT 1", maxrec=1)
    assert len(service.receipts) == 1
    assert service.receipts[0].response_kind == "html"
    assert "SELECT" not in str(service.receipts[0].to_record())


def test_openapi_sql_rejects_more_rows_than_maxrec() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(b'[{"x":1},{"x":2}]')

    with pytest.raises(LamostOpenAPISQLError, match="maxrec"):
        execute_openapi_sql(
            "https://example.test/openapi",
            "dr8",
            "v1.0",
            "SELECT x FROM t",
            maxrec=1,
            retries=0,
            opener=opener,
        )


def test_source_query_error_envelope_remains_redacted_by_default() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(
            b'{"error":"bad request","description":"SELECT * FROM t WHERE id='
            b'123456789012345678"}'
        )

    service = OpenAPISQLService(
        "https://example.test/openapi",
        retries=0,
        opener=opener,
    )
    with pytest.raises(LamostOpenAPISQLError, match="error envelope"):
        service.run_sync("SELECT * FROM t WHERE id=123456789012345678", maxrec=1)
    record = service.receipts[0].to_record()
    assert "diagnostic_error_code" not in record
    assert "diagnostic_error_description" not in record
    assert "123456789012345678" not in str(record)


def test_metadata_probe_can_opt_in_to_sanitized_error_details() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(
            b'{"error":"authorization_required","description":'
            b'"Please provide token; SELECT secret FROM table WHERE id='
            b'123456789012345678"}'
        )

    service = OpenAPISQLService(
        "https://example.test/openapi",
        retries=0,
        diagnostic_error_details=True,
        opener=opener,
    )
    with pytest.raises(LamostOpenAPISQLError, match="authorization_required"):
        service.run_sync(
            "SELECT table_name FROM information_schema.columns",
            maxrec=10,
        )
    record = service.receipts[0].to_record()
    assert record["diagnostic_error_code"] == "authorization_required"
    assert record["diagnostic_error_description"] == "Please provide token; [sql-redacted]"
    assert "123456789012345678" not in str(record)
