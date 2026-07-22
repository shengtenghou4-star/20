from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from hou_compact.datalab import DataLabQueryConfig, DataLabQueryError
from hou_compact.datalab_query_manager import (
    execute_query_manager_csv,
    query_desi_gaia_overlap_v2,
    query_manager_endpoint,
    query_manager_url,
)
from hou_compact.gaia_dr2_bridge import GaiaDr2BridgeConfig
from hou_compact.gaia_dr2_bridge_v2 import (
    _client_order,
    build_gaia_dr2_bridge_adql_v2,
    query_gaia_dr2_neighbourhood_v2,
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


def test_query_manager_endpoint_matches_official_nested_contract() -> None:
    assert query_manager_endpoint("https://datalab.noirlab.edu") == (
        "https://datalab.noirlab.edu/query/query"
    )
    assert query_manager_endpoint("https://datalab.noirlab.edu/query") == (
        "https://datalab.noirlab.edu/query/query"
    )
    assert query_manager_endpoint("https://datalab.noirlab.edu/query/query") == (
        "https://datalab.noirlab.edu/query/query"
    )


def test_query_manager_url_uses_official_parameters() -> None:
    url = query_manager_url(DataLabQueryConfig(), "SELECT 1")
    parsed = urlparse(url)
    parameters = parse_qs(parsed.query, keep_blank_values=True)
    assert parsed.path == "/query/query"
    assert parameters["sql"] == ["SELECT 1"]
    assert parameters["ofmt"] == ["csv"]
    assert parameters["out"] == ["None"]
    assert parameters["async"] == ["False"]
    assert parameters["drop"] == ["False"]


def test_query_manager_batches_and_preserves_large_ids() -> None:
    body = (
        "source_id,targetid,survey,program,healpix,match_distance_arcsec\n"
        "6012345678901234567,39633391000000001,main,bright,21854,0.125\n"
    )

    def opener(request: object, timeout: float) -> _Response:
        assert urlparse(request.full_url).path == "/query/query"
        assert timeout == 10.0
        return _Response(body)

    frame, receipts = query_desi_gaia_overlap_v2(
        [6_012_345_678_901_234_567],
        config=DataLabQueryConfig(timeout_seconds=10.0, retries=0),
        opener=opener,
    )
    assert int(frame.iloc[0]["source_id"]) == 6_012_345_678_901_234_567
    assert int(frame.iloc[0]["targetid"]) == 39_633_391_000_000_001
    assert len(receipts) == 1


def test_query_manager_schema_failure_reports_safe_header_hash() -> None:
    def opener(_request: object, timeout: float) -> _Response:
        del timeout
        return _Response("jobid,status\nabc,COMPLETED\n")

    with pytest.raises(DataLabQueryError, match="response_sha256=.*first_line='jobid,status'"):
        query_desi_gaia_overlap_v2(
            [1],
            config=DataLabQueryConfig(retries=0),
            opener=opener,
        )


def test_query_manager_service_error_fails_closed() -> None:
    def opener(_request: object, timeout: float) -> _Response:
        del timeout
        return _Response("Error: relation does not exist")

    with pytest.raises(DataLabQueryError, match="service error"):
        execute_query_manager_csv(
            "SELECT 1",
            config=DataLabQueryConfig(retries=0),
            opener=opener,
        )


def test_gaia_bridge_adql_has_no_scalar_order_expression() -> None:
    adql = build_gaia_dr2_bridge_adql_v2([20, 10])
    assert "IN (10,20)" in adql
    assert "ABS(" not in adql
    assert (
        "ORDER BY d.dr3_source_id, d.angular_distance, d.dr2_source_id" in adql
    )


def test_client_order_uses_absolute_magnitude_tie_break() -> None:
    frame = pd.DataFrame(
        {
            "dr3_source_id": [1, 1, 1],
            "dr2_source_id": [103, 102, 101],
            "angular_distance_mas": [2.0, 2.0, 2.0],
            "magnitude_difference_mag": [-0.8, 0.3, -0.1],
            "proper_motion_propagation": [True, True, True],
        }
    )
    ordered = _client_order(frame)
    assert ordered["dr2_source_id"].tolist() == [101, 102, 103]


def test_gaia_bridge_v2_batches_with_parser_safe_query() -> None:
    queries: list[str] = []

    def executor(_tap_url: str, adql: str, maxrec: int) -> pd.DataFrame:
        assert maxrec == 10
        queries.append(adql)
        return pd.DataFrame(
            {
                "dr3_source_id": [1],
                "dr2_source_id": [11],
                "angular_distance_mas": [0.2],
                "magnitude_difference_mag": [-0.1],
                "proper_motion_propagation": [True],
            }
        )

    frame, receipts = query_gaia_dr2_neighbourhood_v2(
        [1],
        config=GaiaDr2BridgeConfig(batch_size=1, maxrec_per_batch=10),
        query_executor=executor,
    )
    assert len(frame) == 1
    assert len(receipts) == 1
    assert "ABS(" not in queries[0]
