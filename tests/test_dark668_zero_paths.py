from __future__ import annotations

import pandas as pd

from hou_compact.dark668_dynamics import score_dynamical_consistency
from scripts.score_dark668_keplerian import (
    ensure_dynamics_input_schema,
    normalize_circular_score_schema,
)


def test_all_unscored_period_table_is_a_valid_kepler_input() -> None:
    circular = pd.DataFrame(
        {
            "source_id": [1, 2],
            "status": [
                "insufficient_independent_visits",
                "insufficient_independent_visits",
            ],
        }
    )
    normalized = normalize_circular_score_schema(circular)
    assert normalized is not None
    assert "delta_bic_constant_minus_periodic" in normalized.columns
    assert normalized["delta_bic_constant_minus_periodic"].isna().all()


def test_zero_kepler_survivors_flow_into_dynamical_zero_result() -> None:
    kepler = ensure_dynamics_input_schema(
        pd.DataFrame(
            {
                "source_id": [7],
                "status": ["not_preselected"],
            }
        )
    )
    candidates = pd.DataFrame(
        {
            "source_id": [7],
            "mass": [1.0],
            "radius": [1.0],
            "fit_companion_mass": [4.0],
            "fit_companion_mass_errup": [1.0],
            "fit_companion_mass_errlow": [1.0],
        }
    )
    scored = score_dynamical_consistency(candidates, kepler)
    assert scored.loc[0, "status"] == "not_keplerian_scored"
