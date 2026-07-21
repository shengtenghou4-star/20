import json
from pathlib import Path

import pytest
from astropy.table import Table

from hou_compact.gaia import (
    failure_manifest_path,
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
