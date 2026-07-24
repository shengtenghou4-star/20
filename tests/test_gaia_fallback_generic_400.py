from __future__ import annotations

import json
from pathlib import Path

import pytest

from hou_compact.gaia import failure_manifest_path
from hou_compact.gaia_fallback import (
    AIP_LONG_QUEUE,
    classify_esa_fallback_failure,
    run_async_query_with_quota_fallback,
)


class DALServiceError(RuntimeError):
    """Synthetic PyVO-shaped provider exception for fail-closed classification tests."""


def _generic_400_message() -> str:
    return "400 Client Error: Bad Request for url: https://example.invalid/tap/async"


def test_generic_dalservice_http_400_is_fallback_eligible(tmp_path: Path) -> None:
    output = tmp_path / "gaia.ecsv"
    trigger = classify_esa_fallback_failure(
        DALServiceError(_generic_400_message()),
        output,
    )
    assert trigger == "esa_dalservice_http_400"


def test_generic_http_400_can_be_identified_from_failure_manifest(tmp_path: Path) -> None:
    output = tmp_path / "gaia.ecsv"
    failure_manifest_path(output).write_text(
        json.dumps(
            {
                "error_type": "DALServiceError",
                "error_message": _generic_400_message(),
            }
        ),
        encoding="utf-8",
    )
    trigger = classify_esa_fallback_failure(RuntimeError("generic wrapper"), output)
    assert trigger == "esa_dalservice_http_400"


def test_generic_dalservice_http_400_switches_once_to_aip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text(
        "SELECT TOP 1 source_id FROM gaiadr3.gaia_source",
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def fail_primary(*args, **kwargs):
        raise DALServiceError(_generic_400_message())

    def succeed_fallback(*args, **kwargs):
        calls.append(kwargs)
        return {
            "status": "success",
            "service_provider": "Gaia@AIP",
            "fallback_trigger": kwargs["fallback_trigger"],
        }

    monkeypatch.setattr("hou_compact.gaia_fallback.run_async_query", fail_primary)
    monkeypatch.setattr(
        "hou_compact.gaia_fallback.run_aip_async_query",
        succeed_fallback,
    )

    manifest = run_async_query_with_quota_fallback(query, output, maxrec=5000)

    assert manifest["service_provider"] == "Gaia@AIP"
    assert manifest["fallback_trigger"] == "esa_dalservice_http_400"
    assert len(calls) == 1
    assert calls[0]["queue"] == AIP_LONG_QUEUE
    assert calls[0]["overwrite"] is True
    assert calls[0]["primary_error_type"] == "DALServiceError"


def test_arbitrary_runtime_http_400_does_not_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT broken syntax", encoding="utf-8")

    def fail_primary(*args, **kwargs):
        raise RuntimeError(_generic_400_message())

    def forbidden_fallback(*args, **kwargs):
        raise AssertionError("fallback must not run")

    monkeypatch.setattr("hou_compact.gaia_fallback.run_async_query", fail_primary)
    monkeypatch.setattr(
        "hou_compact.gaia_fallback.run_aip_async_query",
        forbidden_fallback,
    )

    with pytest.raises(RuntimeError, match="400 Client Error"):
        run_async_query_with_quota_fallback(query, output)


def test_non_400_dalservice_failure_does_not_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 1 source_id FROM gaiadr3.gaia_source", encoding="utf-8")

    def fail_primary(*args, **kwargs):
        raise DALServiceError("503 Server Error: Service Unavailable")

    def forbidden_fallback(*args, **kwargs):
        raise AssertionError("fallback must not run")

    monkeypatch.setattr("hou_compact.gaia_fallback.run_async_query", fail_primary)
    monkeypatch.setattr(
        "hou_compact.gaia_fallback.run_aip_async_query",
        forbidden_fallback,
    )

    with pytest.raises(DALServiceError, match="503 Server Error"):
        run_async_query_with_quota_fallback(query, output)
