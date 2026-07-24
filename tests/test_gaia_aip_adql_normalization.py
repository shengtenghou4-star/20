from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from astropy.table import Table

from hou_compact.gaia import success_manifest_path
from hou_compact.gaia_fallback import normalize_aip_adql, run_aip_async_query
from hou_compact.http_timeout import MinimumTimeoutSession


class _DummyResult:
    def __init__(self, table: Table) -> None:
        self._table = table

    def to_table(self) -> Table:
        return self._table


class _SuccessfulJob:
    url = "https://example.invalid/async/synthetic"
    job_id = "synthetic"
    phase = "PENDING"

    def __init__(self, table: Table) -> None:
        self.table = table
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


def test_aip_normalization_rewrites_only_equivalent_join_keyword() -> None:
    original = (
        "SELECT TOP 1 n.source_id\n"
        "FROM gaiadr3.nss_two_body_orbit AS n\n"
        "LEFT   OUTER\nJOIN gaiadr3.astrophysical_parameters AS ap\n"
        "ON n.source_id = ap.source_id\n"
        "ORDER BY n.period DESC\n"
    )
    normalized, count = normalize_aip_adql(original)

    assert count == 1
    assert "LEFT JOIN gaiadr3.astrophysical_parameters" in normalized
    assert "LEFT   OUTER" not in normalized
    assert normalized.startswith("SELECT TOP 1 n.source_id")
    assert normalized.endswith("ORDER BY n.period DESC\n")


def test_aip_normalization_is_noop_without_outer_keyword() -> None:
    original = "SELECT TOP 1 source_id FROM gaiadr3.gaia_source"
    normalized, count = normalize_aip_adql(original)
    assert normalized == original
    assert count == 0


def test_aip_submission_uses_normalized_query_but_hashes_frozen_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_path = tmp_path / "frozen.adql"
    output_path = tmp_path / "gaia.ecsv"
    original = (
        "SELECT TOP 1 n.source_id\n"
        "FROM gaiadr3.nss_two_body_orbit AS n\n"
        "LEFT OUTER JOIN gaiadr3.astrophysical_parameters AS ap\n"
        "ON n.source_id = ap.source_id\n"
    )
    query_path.write_text(original, encoding="utf-8")
    job = _SuccessfulJob(Table({"source_id": [123]}))
    submitted: list[str] = []

    class DummyService:
        def __init__(self, url: str, *, session: MinimumTimeoutSession) -> None:
            assert isinstance(session, MinimumTimeoutSession)

        def submit_job(self, text: str, *, maxrec: int | None, queue: str):
            submitted.append(text)
            assert maxrec == 1
            assert queue == "2h"
            return job

    monkeypatch.setattr("hou_compact.gaia_fallback.pyvo.dal.TAPService", DummyService)

    manifest = run_aip_async_query(
        query_path,
        output_path,
        overwrite=True,
        maxrec=1,
        wait_timeout_seconds=900.0,
        fetch_retries=2,
        queue="2h",
    )

    assert submitted == [original.replace("LEFT OUTER JOIN", "LEFT JOIN")]
    assert manifest["provider_query_normalization_count"] == 1
    assert manifest["frozen_query_provenance_preserved"] is True
    assert manifest["query_sha256"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
    persisted = json.loads(success_manifest_path(output_path).read_text(encoding="utf-8"))
    assert persisted["query_sha256"] == manifest["query_sha256"]
    assert persisted["provider_query_normalization"] == "LEFT OUTER JOIN -> LEFT JOIN"
    assert job.deleted is True
