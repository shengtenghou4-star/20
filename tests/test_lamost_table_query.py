from __future__ import annotations

from dataclasses import dataclass
import json

import pandas as pd
import pytest

from hou_compact.lamost_table_query import (
    LamostTableQueryError,
    post_table_query,
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


def _query(obsid: str = "195309107") -> dict[str, object]:
    return {
        "column_constraints": [
            {
                "column_name": "obsid",
                "constraint": obsid,
                "operation": "equal",
            }
        ],
        "order": "asc",
        "output.fmt": "json",
        "page": 1,
        "pos": {
            "proximity": {
                "defaultRadius": 2,
                "proximity_nearestonly": False,
                "radecTextarea": "11.455864,34.420161,2.0",
            }
        },
        "pos_group": "ra,dec",
        "rows": 5,
        "showcol": ["obsid", "rv", "rv_err"],
        "sort": "obsid",
    }


def test_table_query_posts_json_and_returns_rows_without_token() -> None:
    observed: dict[str, object] = {}

    def opener(request: object, *, timeout: float) -> _Response:
        observed["method"] = getattr(request, "method")
        observed["url"] = str(getattr(request, "full_url"))
        observed["body"] = json.loads(bytes(getattr(request, "data")).decode("utf-8"))
        assert timeout == 12.0
        return _Response(b'[{"obsid":195309107,"rv":12.5,"rv_err":1.2}]')

    frame, receipt = post_table_query(
        "https://example.test/openapi",
        dr_version="dr8",
        sub_version="v2.0",
        table_name="combined",
        query=_query(),
        timeout=12.0,
        retries=0,
        opener=opener,
    )
    expected = pd.DataFrame({"obsid": [195309107], "rv": [12.5], "rv_err": [1.2]})
    pd.testing.assert_frame_equal(frame, expected)
    assert observed["method"] == "POST"
    assert observed["url"] == "https://example.test/openapi/dr8/v2.0/query/combined"
    assert observed["body"] == _query()
    record = receipt.to_record()
    assert record["returned_columns"] == ("obsid", "rv", "rv_err")
    assert record["row_count"] == 1
    assert "195309107" not in str(record)
    assert "11.455864" not in str(record)


def test_table_query_accepts_rows_envelope() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(
            b'{"columns":["obsid","rv","rv_err"],'
            b'"rows":[[10,2.5,0.4],[11,3.0,0.5]]}'
        )

    frame, receipt = post_table_query(
        "https://example.test/openapi",
        dr_version="dr8",
        sub_version="v2.0",
        table_name="combined",
        query=_query("10"),
        retries=0,
        opener=opener,
    )
    assert list(frame.columns) == ["obsid", "rv", "rv_err"]
    assert len(frame) == 2
    assert receipt.row_count == 2


def test_table_query_sanitizes_error_envelope() -> None:
    def opener(request: object, *, timeout: float) -> _Response:
        del request, timeout
        return _Response(
            b'{"error":"validation failed","description":'
            b'"obsid 195309107 at https://example.test/private"}'
        )

    with pytest.raises(LamostTableQueryError, match="validation failed") as captured:
        post_table_query(
            "https://example.test/openapi",
            dr_version="dr8",
            sub_version="v2.0",
            table_name="combined",
            query=_query(),
            retries=0,
            opener=opener,
        )
    receipt = captured.value.receipt
    assert receipt is not None
    record = receipt.to_record()
    assert record["diagnostic_error_code"] == "validation failed"
    assert record["diagnostic_error_description"] == (
        "obsid [number-redacted] at [url-redacted]"
    )
    assert "195309107" not in str(record)
    assert "example.test/private" not in str(record)


def test_table_query_rejects_unsafe_table_name() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        post_table_query(
            "https://example.test/openapi",
            dr_version="dr8",
            sub_version="v2.0",
            table_name="combined;drop table",
            query=_query(),
        )
