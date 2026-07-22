from __future__ import annotations

import json
from io import BytesIO

import pytest

from hou_compact.lamost_sql import (
    LAMOSTSQLError,
    probe_public_sql_protocol,
    submit_sql,
    summarize_payload_shape,
)


class FakeResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return BytesIO(self._body).read(size)


def test_submit_sql_uses_public_json_endpoint() -> None:
    seen: dict[str, object] = {}

    def opener(request: object, **kwargs: object) -> FakeResponse:
        seen["url"] = request.full_url
        return FakeResponse({"sqlid": "abc123"})

    payload, receipt = submit_sql(
        "https://example.org/openapi",
        dr_version="dr8",
        sub_version="v1.0",
        sql="SELECT 1",
        opener=opener,
    )
    assert payload == {"sqlid": "abc123"}
    assert "sql=SELECT+1" in str(seen["url"])
    assert "output.fmt=json" in str(seen["url"])
    assert "token=" not in str(seen["url"])
    assert receipt.url_without_query.endswith("/dr8/v1.0/sql")


def test_api_error_is_rejected() -> None:
    def opener(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse({"error": "Bad Request", "description": "invalid SQL"})

    with pytest.raises(LAMOSTSQLError, match="API error"):
        submit_sql(
            "https://example.org/openapi",
            dr_version="dr8",
            sub_version="v1.0",
            sql="SELECT 1",
            opener=opener,
        )


def test_constant_probe_contains_no_catalogue_query() -> None:
    def opener(request: object, **kwargs: object) -> FakeResponse:
        assert "SELECT+1+AS+hou_compact_probe" in request.full_url
        return FakeResponse([{"hou_compact_probe": 1}])

    result = probe_public_sql_protocol(
        openapi_root="https://example.org/openapi",
        opener=opener,
    )
    assert result["status"] == "pass"
    assert result["response_shape"]["row_count"] == 1
    assert result["response"] == [{"hou_compact_probe": 1}]


def test_payload_shape_captures_sqlid_without_rows() -> None:
    assert summarize_payload_shape({"sqlid": "xyz", "status": "queued"}) == {
        "payload_type": "dict",
        "top_level_keys": ["sqlid", "status"],
        "sqlid": "xyz",
        "status": "queued",
    }
