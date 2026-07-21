import json
from pathlib import Path

import pytest
from astropy.table import Table

from hou_compact.gaia import (
    failure_manifest_path,
    run_async_query,
    run_sync_query,
    success_manifest_path,
)


class _DummyResult:
    def __init__(self, table: Table) -> None:
        self._table = table

    def to_table(self) -> Table:
        return self._table


def test_success_manifest_records_schema_and_checksum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 1 source_id FROM gaiadr3.gaia_source", encoding="utf-8")
    table = Table({"source_id": [123]})

    class DummyService:
        def __init__(self, url: str) -> None:
            self.url = url

        def search(self, text: str) -> _DummyResult:
            assert "source_id" in text
            return _DummyResult(table)

    monkeypatch.setattr("hou_compact.gaia.pyvo.dal.TAPService", DummyService)
    manifest = run_sync_query(query, output, tap_url="https://example.invalid/tap")
    assert manifest["status"] == "success"
    assert manifest["execution_mode"] == "sync"
    assert manifest["row_count"] == 1
    assert manifest["column_names"] == ["source_id"]
    assert success_manifest_path(output).exists()
    assert not failure_manifest_path(output).exists()


def test_network_failure_writes_separate_failure_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 1 source_id FROM gaiadr3.gaia_source", encoding="utf-8")

    class FailingService:
        def __init__(self, url: str) -> None:
            self.url = url

        def search(self, text: str) -> object:
            raise RuntimeError("synthetic Gaia TAP failure")

    monkeypatch.setattr("hou_compact.gaia.pyvo.dal.TAPService", FailingService)
    with pytest.raises(RuntimeError, match="synthetic Gaia TAP failure"):
        run_sync_query(query, output, tap_url="https://example.invalid/tap")

    path = failure_manifest_path(output)
    assert path.exists()
    failure = json.loads(path.read_text(encoding="utf-8"))
    assert failure["status"] == "failure"
    assert failure["execution_mode"] == "sync"
    assert failure["error_type"] == "RuntimeError"
    assert failure["error_message"] == "synthetic Gaia TAP failure"
    assert failure["output_exists"] is False
    assert not success_manifest_path(output).exists()


def test_existing_output_refusal_does_not_overwrite_success_manifest(tmp_path: Path) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 1 source_id FROM gaiadr3.gaia_source", encoding="utf-8")
    output.write_text("existing", encoding="utf-8")
    success = success_manifest_path(output)
    success.write_text('{"status":"success","sentinel":true}', encoding="utf-8")

    with pytest.raises(FileExistsError):
        run_sync_query(query, output)

    assert json.loads(success.read_text(encoding="utf-8"))["sentinel"] is True
    assert not failure_manifest_path(output).exists()


class _SuccessfulAsyncJob:
    url = "https://example.invalid/tap/async/123"
    job_id = "123"
    phase = "PENDING"

    def __init__(self, table: Table) -> None:
        self.table = table
        self.execution_duration = 60.0
        self.deleted = False

    def run(self):
        self.phase = "QUEUED"
        return self

    def wait(self, *, timeout: float):
        assert timeout == 900.0
        self.phase = "COMPLETED"
        return self

    def raise_if_error(self) -> None:
        return None

    def fetch_result(self, *, max_retries: int) -> _DummyResult:
        assert max_retries == 2
        return _DummyResult(self.table)

    def delete(self) -> None:
        self.deleted = True


class _FailedAsyncJob(_SuccessfulAsyncJob):
    def wait(self, *, timeout: float):
        assert timeout == 900.0
        self.phase = "ERROR"
        return self

    def raise_if_error(self) -> None:
        raise RuntimeError("remote Gaia job failed")


def test_async_query_records_job_provenance_and_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 2 source_id FROM gaiadr3.gaia_source", encoding="utf-8")
    table = Table({"source_id": [123, 456]})
    job = _SuccessfulAsyncJob(table)

    class DummyAsyncService:
        def __init__(self, url: str) -> None:
            self.url = url

        def submit_job(self, text: str, *, maxrec: int | None):
            assert "source_id" in text
            assert maxrec == 500
            return job

    monkeypatch.setattr("hou_compact.gaia.pyvo.dal.TAPService", DummyAsyncService)
    manifest = run_async_query(
        query,
        output,
        tap_url="https://example.invalid/tap",
        maxrec=500,
        execution_duration_seconds=1800.0,
        wait_timeout_seconds=900.0,
        fetch_retries=2,
    )
    assert manifest["status"] == "success"
    assert manifest["execution_mode"] == "async"
    assert manifest["job_id"] == "123"
    assert manifest["terminal_phase"] == "COMPLETED"
    assert manifest["row_count"] == 2
    assert job.execution_duration == 1800.0
    assert job.deleted is True
    assert success_manifest_path(output).exists()
    assert not failure_manifest_path(output).exists()


def test_async_failure_records_remote_phase_and_deletes_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 2 source_id FROM gaiadr3.gaia_source", encoding="utf-8")
    job = _FailedAsyncJob(Table({"source_id": []}))

    class FailingAsyncService:
        def __init__(self, url: str) -> None:
            self.url = url

        def submit_job(self, text: str, *, maxrec: int | None):
            assert maxrec == 500
            return job

    monkeypatch.setattr("hou_compact.gaia.pyvo.dal.TAPService", FailingAsyncService)
    with pytest.raises(RuntimeError, match="remote Gaia job failed"):
        run_async_query(
            query,
            output,
            tap_url="https://example.invalid/tap",
            maxrec=500,
            wait_timeout_seconds=900.0,
            fetch_retries=2,
        )
    failure = json.loads(failure_manifest_path(output).read_text(encoding="utf-8"))
    assert failure["status"] == "failure"
    assert failure["execution_mode"] == "async"
    assert failure["terminal_phase"] == "ERROR"
    assert failure["job_url"].endswith("/123")
    assert failure["error_type"] == "RuntimeError"
    assert job.deleted is True


def test_async_query_validates_limits_before_network(tmp_path: Path) -> None:
    query = tmp_path / "pilot.adql"
    output = tmp_path / "pilot.ecsv"
    query.write_text("SELECT TOP 1 source_id FROM gaiadr3.gaia_source", encoding="utf-8")
    with pytest.raises(ValueError, match="maxrec"):
        run_async_query(query, output, maxrec=0)
    with pytest.raises(ValueError, match="wait_timeout_seconds"):
        run_async_query(query, output, wait_timeout_seconds=0.0)
    with pytest.raises(ValueError, match="fetch_retries"):
        run_async_query(query, output, fetch_retries=-1)
