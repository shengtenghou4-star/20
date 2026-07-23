from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.apogee_dr17 import (
    ApogeeDR17Error,
    build_exact_visit_query,
    build_sample_query,
    standardize_exact_visits,
)


def test_queries_use_exact_identity_and_official_visit_join() -> None:
    sample = build_sample_query()
    assert "apogeeStarAllVisit" in sample
    assert "v.vhelio" in sample
    assert "v.vrelerr" in sample
    exact = build_exact_visit_query(
        [2676113965163724160, 1234567890123456789]
    )
    assert "gaiaedr3_source_id IN" in exact
    assert "SELECT DISTINCT" in exact
    with pytest.raises(ValueError, match="at most 40"):
        build_exact_visit_query(range(1, 42))


def test_standardize_exact_visits_enforces_identity_and_quality() -> None:
    frame = pd.DataFrame(
        {
            "gaiaedr3_source_id": [
                "2676113965163724160",
                "2676113965163724160",
                "999999999999999999",
            ],
            "visit_id": ["visit-a", "visit-b", "visit-c"],
            "mjd": [59000, 59001, 59002],
            "jd": [2459000.5, 2459001.5, 2459002.5],
            "vhelio": [12.0, 14.0, 99.0],
            "vrelerr": [0.2, 0.3, 0.1],
            "snr": [50.0, 10.0, 50.0],
            "starflag": [0, 0, 0],
            "telescope": ["apo25m", "apo25m", "apo25m"],
            "survey": ["apogee2", "apogee2", "apogee2"],
        }
    )
    rows = standardize_exact_visits(frame, [2676113965163724160])
    assert len(rows) == 2
    assert set(rows["source_id"].astype(int)) == {2676113965163724160}
    assert int(rows["success"].sum()) == 1
    assert rows["obsid"].is_unique
    assert rows.loc[rows["mjd"].eq(59001), "rvs_warn"].iloc[0] == 1
    assert rows["source_match_mode"].eq(
        "exact_gaia_edr3_integer_skyserver_join"
    ).all()


def test_standardize_exact_visits_rejects_duplicate_visit_id() -> None:
    frame = pd.DataFrame(
        {
            "gaiaedr3_source_id": [1, 1],
            "visit_id": ["same", "same"],
            "mjd": [59000, 59001],
            "jd": [2459000.5, 2459001.5],
            "vhelio": [1.0, 2.0],
            "vrelerr": [0.1, 0.1],
            "snr": [30.0, 30.0],
            "starflag": [0, 0],
            "telescope": ["apo25m", "apo25m"],
            "survey": ["apogee2", "apogee2"],
        }
    )
    with pytest.raises(ApogeeDR17Error, match="duplicate visit_id"):
        standardize_exact_visits(frame, [1])
