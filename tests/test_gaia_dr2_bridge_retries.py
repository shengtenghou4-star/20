from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.gaia_dr2_bridge import GaiaDr2BridgeConfig, GaiaDr2BridgeError
from hou_compact.gaia_dr2_bridge_v2 import query_gaia_dr2_neighbourhood_v2


def _valid_neighbours() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "dr3_source_id": [101, 102],
            "dr2_source_id": [201, 202],
            "angular_distance_mas": [1.0, 2.0],
            "magnitude_difference_mag": [0.1, -0.2],
            "proper_motion_propagation": [True, False],
        }
    )


def test_transient_batch_failures_are_retried_without_losing_the_batch() -> None:
    calls = 0

    def flaky_executor(tap_url: str, adql: str, maxrec: int) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        assert tap_url.startswith("https://")
        assert "101,102" in adql
        assert maxrec == 20
        if calls < 3:
            raise ConnectionError("temporary Gaia TAP outage")
        return _valid_neighbours()

    neighbours, receipts = query_gaia_dr2_neighbourhood_v2(
        [101, 102],
        config=GaiaDr2BridgeConfig(batch_size=2, maxrec_per_batch=20),
        query_executor=flaky_executor,
        query_retries=4,
        retry_backoff_seconds=0,
    )

    assert calls == 3
    assert list(neighbours["dr3_source_id"]) == [101, 102]
    assert len(receipts) == 1
    assert receipts[0].requested_source_count == 2
    assert receipts[0].returned_source_count == 2


def test_response_contract_failure_is_not_retried() -> None:
    calls = 0

    def invalid_executor(tap_url: str, adql: str, maxrec: int) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return pd.DataFrame({"dr3_source_id": [101]})

    with pytest.raises(GaiaDr2BridgeError, match="missing columns"):
        query_gaia_dr2_neighbourhood_v2(
            [101],
            config=GaiaDr2BridgeConfig(batch_size=1, maxrec_per_batch=10),
            query_executor=invalid_executor,
            query_retries=5,
            retry_backoff_seconds=0,
        )

    assert calls == 1


def test_exhausted_transient_retries_report_attempt_count() -> None:
    calls = 0

    def failing_executor(tap_url: str, adql: str, maxrec: int) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise TimeoutError("Gaia TAP did not answer")

    with pytest.raises(GaiaDr2BridgeError, match="failed after 3 attempts"):
        query_gaia_dr2_neighbourhood_v2(
            [101],
            config=GaiaDr2BridgeConfig(batch_size=1, maxrec_per_batch=10),
            query_executor=failing_executor,
            query_retries=2,
            retry_backoff_seconds=0,
        )

    assert calls == 3
