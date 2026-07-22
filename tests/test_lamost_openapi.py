from __future__ import annotations

import json
from io import BytesIO

import pytest

from hou_compact.lamost_openapi import (
    LAMOSTOpenAPIError,
    REQUIRED_MULTIEPOCH_COLUMNS,
    candidate_metadata_nodes,
    extract_tap_urls,
    fetch_json,
    safe_metadata_summary,
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


def test_fetch_json_preserves_receipt() -> None:
    def opener(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse({"status": "ok"})

    payload, receipt = fetch_json(
        "https://example.org/metadata",
        opener=opener,
    )
    assert payload == {"status": "ok"}
    assert receipt.status == 200
    assert receipt.response_bytes > 0
    assert len(receipt.sha256) == 64


def test_candidate_metadata_nodes_and_tap_urls() -> None:
    payload = {
        "tables": [
            {
                "table_name": "lrs_multiple_epoch",
                "columns": list(REQUIRED_MULTIEPOCH_COLUMNS),
            }
        ]
    }
    nodes = candidate_metadata_nodes(payload)
    assert any(node.get("table_name") == "lrs_multiple_epoch" for node in nodes)
    assert extract_tap_urls({"tap_url": "https://example.org/tap"}) == [
        "https://example.org/tap"
    ]


def test_safe_metadata_summary_does_not_emit_nested_source_rows() -> None:
    node = {
        "table_name": "lrs_multiple_epoch",
        "columns": list(REQUIRED_MULTIEPOCH_COLUMNS),
        "rows": [{"gaia_source_id": "123"}],
    }
    summary = safe_metadata_summary(node)
    assert summary["table_name"] == "lrs_multiple_epoch"
    assert "rows" not in summary
    assert "123" not in str(summary)


def test_fetch_json_rejects_oversized_response() -> None:
    def opener(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse({"payload": "x" * 2000})

    with pytest.raises(LAMOSTOpenAPIError, match="exceeded"):
        fetch_json(
            "https://example.org/metadata",
            maximum_response_bytes=1024,
            opener=opener,
        )
