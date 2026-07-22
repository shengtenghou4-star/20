from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from hou_compact.datalab import (
    DataLabQueryConfig,
    DataLabQueryError,
    build_desi_gaia_overlap_sql,
    execute_sync_csv_query,
    parse_desi_gaia_overlap_csv,
    query_desi_gaia_overlap,
)


class _Response:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, maximum: int = -1) -> bytes:
        return self._body if maximum < 0 else self._body[:maximum]


def test_sql_uses_reverse_crossmatch_and_exact_zpix_join() -> None:
    sql = build_desi_gaia_overlap_sql([20, 10, 20])
    assert "gaia_dr3.x1p5__gaia_source__desi_dr1__zpix AS x" in sql
    assert "JOIN desi_dr1.zpix AS z ON x.id2 = z.id" in sql
    assert "x.id1 IN (10,20)" in sql
    assert "CAST(" not in sql
    assert "z.program IN ('bright','dark')" in sql


def test_unsafe_program_literal_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsafe programs"):
        build_desi_gaia_overlap_sql([1], programs=("bright';drop table zpix;--",))


def test_parse_preserves_large_integer_identifiers() -> None:
    text = (
        "source_id,targetid,survey,program,healpix,match_distance_arcsec\n"
        "6012345678901234567,39633391000000001,main,bright,21854,0.125\n"
    )
    frame = parse_desi_gaia_overlap_csv(text)
    assert int(frame.iloc[0]["source_id"]) == 6_012_345_678_901_234_567
    assert int(frame.iloc[0]["targetid"]) == 39_633_391_000_000_001
    assert frame.iloc[0]["program"] == "bright"


def test_query_batches_and_deduplicates_exact_rows() -> None:
    responses = [
        (
            "source_id,targetid,survey,program,healpix,match_distance_arcsec\n"
            "1,101,main,bright,10,0.2\n"
            "1,101,main,bright,10,0.2\n"
        ),
        (
            "source_id,targetid,survey,program,healpix,match_distance_arcsec\n"
            "3,303,main,dark,30,1.1\n"
        ),
    ]
    requested_sql: list[str] = []

    def opener(request: object, timeout: float) -> _Response:
        assert timeout == 10.0
        query = parse_qs(urlparse(request.full_url).query)
        requested_sql.append(query["sql"][0])
        return _Response(responses[len(requested_sql) - 1])

    config = DataLabQueryConfig(batch_size=2, timeout_seconds=10.0, retries=0)
    frame, receipts = query_desi_gaia_overlap(
        [3, 2, 1],
        config=config,
        opener=opener,
    )
    assert frame[["source_id", "targetid"]].values.tolist() == [[1, 101], [3, 303]]
    assert len(receipts) == 2
    assert receipts[0].requested_source_count == 2
    assert receipts[0].returned_row_count == 2
    assert receipts[1].returned_source_count == 1
    assert "x.id1 IN (1,2)" in requested_sql[0]
    assert "x.id1 IN (3)" in requested_sql[1]


def test_service_error_payload_fails_closed() -> None:
    config = DataLabQueryConfig(retries=0)

    def opener(_request: object, timeout: float) -> _Response:
        assert timeout == config.timeout_seconds
        return _Response("Error: relation does not exist")

    with pytest.raises(DataLabQueryError, match="service error"):
        execute_sync_csv_query("SELECT 1", config=config, opener=opener)


def test_response_with_unknown_source_is_rejected() -> None:
    text = (
        "source_id,targetid,survey,program,healpix,match_distance_arcsec\n"
        "999,1,main,bright,1,0.1\n"
    )

    def opener(_request: object, timeout: float) -> _Response:
        del timeout
        return _Response(text)

    with pytest.raises(DataLabQueryError, match="outside the current batch"):
        query_desi_gaia_overlap(
            [1],
            config=DataLabQueryConfig(retries=0),
            opener=opener,
        )


def test_empty_csv_header_is_valid_zero_overlap() -> None:
    text = "source_id,targetid,survey,program,healpix,match_distance_arcsec\n"
    frame = parse_desi_gaia_overlap_csv(text)
    assert isinstance(frame, pd.DataFrame)
    assert frame.empty
