from __future__ import annotations

import json
from pathlib import Path

import pytest
from astropy.table import Table

from hou_compact.gaia import failure_manifest_path, success_manifest_path
from hou_compact.gaia_fallback import (
    AIP_GAIA_TAP_URL,
    AIP_LONG_QUEUE,
    is_esa_anonymous_quota_failure,
    run_aip_async_query,
    run_async_query_with_quota_fallback,
)
from hou_compact.http_timeout import MinimumTimeoutSession


class _DummyResult:
    def __init__(self, table: Table) -> None:
        self._table = table

    def to_table(self) -> Table:
        return self._table


class _SuccessfulAipJob:
    url = "https://gaia.aip.de/tap/async/synthetic"
    job_id = "synthetic"
    phase = "PENDING"

    def __init__(self, table: Table) -> None:
        self.table = table
        self.deleted = False
        self.wait_timeouts: list[float] = []

    def run(self):
        self.phase = "QUEUED"
        return self

    def wait(self, *, timeout: float):
        self.wait_timeouts.append(timeout)
        self.phase = "COMPLETED"
        return self

    def raise_if_error(self) -> None:
        return None

    def fetch_result(self, *, max_retries: int) -> _DummyResult:
        assert max_retries == 2
        return _DummyResult(self.table)

    def delete(self) -> None:
        self.deleted = True


def _quota_message() -> str:
    return (
        "Filesystem quota exceeded for user anonymous (Currently using 200 GB, "
        "increasing it exceeds allowed value)."
    )


def test_explicit_anonymous_quota_failure_is_detected_from_error(tmp_path: Path) -> None:
    output = tmp_path / "gaia.ecsv"
    assert is_esa_anonymous_quota_failure(RuntimeError(_quota_message()), output)


def test_quota_detection_can_use_immutable_failure_manifest(tmp_path: Path) -> None:
    output = tmp_path / "gaia.ecsv"
    failure_manifest_path(output).write_text(
        json.dumps({"error_message": _quota_message()}),
        encoding="utf-8",
    )
    assert is_esa_anonymous_quota_failure(RuntimeError("generic wrapper"), output)


def test_quota_failure_switches_once_to_aip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 1 source_id FROM gaiadr3.gaia_source", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def fail_primary(*args, **kwargs):
        raise RuntimeError(_quota_message())

    def succeed_fallback(*args, **kwargs):
        calls.append(kwargs)
        return {"status": "success", "service_provider": "Gaia@AIP"}

    monkeypatch.setattr("hou_compact.gaia_fallback.run_async_query", fail_primary)
    monkeypatch.setattr("hou_compact.gaia_fallback.run_aip_async_query", succeed_fallback)

    manifest = run_async_query_with_quota_fallback(
        query,
        output,
        maxrec=5000,
        wait_timeout_seconds=2700.0,
        fetch_retries=4,
    )

    assert manifest["service_provider"] == "Gaia@AIP"
    assert len(calls) == 1
    assert calls[0]["queue"] == AIP_LONG_QUEUE
    assert calls[0]["overwrite"] is True
    assert calls[0]["maxrec"] == 5000
    assert calls[0]["primary_error_type"] == "RuntimeError"


def test_nonquota_failure_never_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT broken syntax", encoding="utf-8")

    def fail_primary(*args, **kwargs):
        raise RuntimeError("synthetic ADQL validation failure")

    def forbidden_fallback(*args, **kwargs):
        raise AssertionError("fallback must not run")

    monkeypatch.setattr("hou_compact.gaia_fallback.run_async_query", fail_primary)
    monkeypatch.setattr("hou_compact.gaia_fallback.run_aip_async_query", forbidden_fallback)

    with pytest.raises(RuntimeError, match="ADQL validation failure"):
        run_async_query_with_quota_fallback(query, output)


def test_aip_async_queue_and_fallback_provenance_are_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 1 source_id FROM gaiadr3.gaia_source", encoding="utf-8")
    table = Table({"source_id": [123]})
    job = _SuccessfulAipJob(table)

    class DummyAipService:
        def __init__(self, url: str, *, session: MinimumTimeoutSession) -> None:
            assert url == AIP_GAIA_TAP_URL
            assert isinstance(session, MinimumTimeoutSession)

        def submit_job(self, text: str, *, maxrec: int | None, queue: str):
            assert "source_id" in text
            assert maxrec == 100
            assert queue == "2h"
            return job

    monkeypatch.setattr("hou_compact.gaia_fallback.pyvo.dal.TAPService", DummyAipService)
    manifest = run_aip_async_query(
        query,
        output,
        overwrite=True,
        maxrec=100,
        wait_timeout_seconds=900.0,
        fetch_retries=2,
        queue="2h",
        primary_error_type="DALQueryError",
    )

    assert manifest["status"] == "success"
    assert manifest["tap_url"] == AIP_GAIA_TAP_URL
    assert manifest["service_provider"] == "Gaia@AIP"
    assert manifest["async_queue"] == "2h"
    assert manifest["fallback_trigger"] == "esa_anonymous_filesystem_quota"
    assert manifest["primary_error_type"] == "DALQueryError"
    assert manifest["terminal_phase"] == "COMPLETED"
    assert job.wait_timeouts == [900.0]
    assert job.deleted is True
    assert success_manifest_path(output).exists()
    assert not failure_manifest_path(output).exists()


def test_invalid_aip_queue_fails_before_network(tmp_path: Path) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 1 source_id FROM gaiadr3.gaia_source", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported Gaia@AIP queue"):
        run_aip_async_query(query, output, queue="unbounded")
