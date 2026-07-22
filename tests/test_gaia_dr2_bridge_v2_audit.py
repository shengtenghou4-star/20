import pandas as pd

from hou_compact.gaia_dr2_bridge_v2 import audit_gaia_dr2_bridge_v2


def test_audit_uses_absolute_magnitude_difference_for_equal_distance() -> None:
    neighbours = pd.DataFrame(
        {
            "dr3_source_id": [1, 1, 1],
            "dr2_source_id": [103, 102, 101],
            "angular_distance_mas": [2.0, 2.0, 2.0],
            "magnitude_difference_mag": [-0.8, 0.3, -0.1],
            "proper_motion_propagation": [True, True, True],
        }
    )
    audited = audit_gaia_dr2_bridge_v2(
        neighbours,
        minimum_distance_margin_mas=0.0,
    )
    assert int(audited.iloc[0]["dr2_source_id"]) == 101
    assert audited.iloc[0]["dr2_magnitude_difference_mag"] == -0.1


def test_audit_still_rejects_equal_distance_as_ambiguous_under_default_margin() -> None:
    neighbours = pd.DataFrame(
        {
            "dr3_source_id": [1, 1],
            "dr2_source_id": [11, 12],
            "angular_distance_mas": [2.0, 2.0],
            "magnitude_difference_mag": [0.1, 0.2],
            "proper_motion_propagation": [True, True],
        }
    )
    audited = audit_gaia_dr2_bridge_v2(neighbours)
    assert audited.iloc[0]["dr2_bridge_status"] == "rejected_ambiguous_nearest"
