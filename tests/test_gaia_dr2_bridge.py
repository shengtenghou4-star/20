import pandas as pd
import pytest

from hou_compact.gaia_dr2_bridge import (
    GaiaDr2BridgeConfig,
    GaiaDr2BridgeError,
    audit_gaia_dr2_bridge,
    build_gaia_dr2_bridge_adql,
    query_gaia_dr2_neighbourhood,
)


def test_bridge_query_uses_official_neighbourhood_table() -> None:
    adql = build_gaia_dr2_bridge_adql([20, 10, 20])
    assert "FROM gaiadr3.dr2_neighbourhood AS d" in adql
    assert "d.dr3_source_id IN (10,20)" in adql
    assert "angular_distance_mas" in adql


def test_bridge_batches_and_preserves_all_neighbours() -> None:
    calls: list[str] = []

    def executor(_tap_url: str, adql: str, maxrec: int) -> pd.DataFrame:
        calls.append(adql)
        assert maxrec == 100
        if len(calls) == 1:
            return pd.DataFrame(
                {
                    "dr3_source_id": [1, 1, 2],
                    "dr2_source_id": [101, 102, 202],
                    "angular_distance_mas": [2.0, 20.0, 1.0],
                    "magnitude_difference_mag": [0.01, 1.0, 0.02],
                    "proper_motion_propagation": [True, True, False],
                }
            )
        return pd.DataFrame(
            {
                "dr3_source_id": [3],
                "dr2_source_id": [303],
                "angular_distance_mas": [3.0],
                "magnitude_difference_mag": [0.03],
                "proper_motion_propagation": [True],
            }
        )

    frame, receipts = query_gaia_dr2_neighbourhood(
        [3, 2, 1],
        config=GaiaDr2BridgeConfig(batch_size=2, maxrec_per_batch=100),
        query_executor=executor,
    )
    assert len(frame) == 4
    assert len(receipts) == 2
    assert receipts[0].returned_source_count == 2
    assert "IN (1,2)" in calls[0]
    assert "IN (3)" in calls[1]


def test_audit_accepts_separated_nearest_and_rejects_ambiguity() -> None:
    neighbours = pd.DataFrame(
        {
            "dr3_source_id": [1, 1, 2, 2, 3],
            "dr2_source_id": [101, 102, 201, 202, 301],
            "angular_distance_mas": [2.0, 20.0, 5.0, 7.0, 2000.0],
            "magnitude_difference_mag": [0.0, 0.5, 0.1, 0.1, 0.0],
            "proper_motion_propagation": [True, True, True, True, False],
        }
    )
    result = audit_gaia_dr2_bridge(
        neighbours,
        maximum_nearest_distance_mas=1000.0,
        minimum_distance_margin_mas=5.0,
    ).set_index("source_id")
    assert result.loc[1, "dr2_bridge_status"] == "accepted_unique_or_separated_nearest"
    assert result.loc[1, "dr2_source_id"] == 101
    assert result.loc[2, "dr2_bridge_status"] == "rejected_ambiguous_nearest"
    assert result.loc[3, "dr2_bridge_status"] == "rejected_nearest_too_distant"


def test_bridge_rejects_source_outside_current_batch() -> None:
    def executor(_tap_url: str, _adql: str, _maxrec: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "dr3_source_id": [999],
                "dr2_source_id": [1],
                "angular_distance_mas": [1.0],
                "magnitude_difference_mag": [0.0],
                "proper_motion_propagation": [True],
            }
        )

    with pytest.raises(GaiaDr2BridgeError, match="outside the current batch"):
        query_gaia_dr2_neighbourhood(
            [1],
            config=GaiaDr2BridgeConfig(batch_size=1, maxrec_per_batch=10),
            query_executor=executor,
        )


def test_bridge_maxrec_saturation_fails_closed() -> None:
    def executor(_tap_url: str, _adql: str, maxrec: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "dr3_source_id": [1] * maxrec,
                "dr2_source_id": range(100, 100 + maxrec),
                "angular_distance_mas": range(maxrec),
                "magnitude_difference_mag": [0.0] * maxrec,
                "proper_motion_propagation": [True] * maxrec,
            }
        )

    with pytest.raises(GaiaDr2BridgeError, match="reached maxrec"):
        query_gaia_dr2_neighbourhood(
            [1],
            config=GaiaDr2BridgeConfig(batch_size=1, maxrec_per_batch=10),
            query_executor=executor,
        )
