from __future__ import annotations

import pandas as pd
import pytest

from hou_compact.dark668 import (
    CatalogueSpec,
    candidate_safe_summary,
    promising_subset,
    rank_promising_targets,
    validate_catalogue,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": ["1", "2", "3", "4"],
            "ra": [1.0, 2.0, 3.0, 4.0],
            "dec": [1.0, 2.0, 3.0, 4.0],
            "parallax": [2.0, 5.0, 1.0, 4.0],
            "parallax_error": [0.2, 0.1, 0.5, 0.2],
            "phot_g_mean_mag": [12.0, 10.0, 14.0, 11.0],
            "ruwe": [2.0, 3.0, 1.1, 2.2],
            "rv_amplitude_robust": [10.0, 20.0, 5.0, 30.0],
            "rv_nb_transits": [12, 20, 5, 25],
            "mass": [1.0, 1.1, 0.9, 1.2],
            "radius": [4.0, 5.0, 1.0, 6.0],
            "fit_period": [300.0, 500.0, 100.0, 700.0],
            "fit_period_errup": [30.0, 20.0, 50.0, 10.0],
            "fit_period_errlow": [20.0, 20.0, 40.0, 10.0],
            "fit_companion_mass": [4.0, 8.0, 5.0, 2.5],
            "fit_companion_mass_errup": [1.0, 0.5, 2.0, 0.5],
            "fit_companion_mass_errlow": [0.8, 0.4, 1.5, 0.5],
            "mass_significance": [0.80, 0.99, 0.70, 0.90],
            "flag_quality": [True, True, False, True],
            "population": ["RGB", "RGB", "MS", "MS"],
        }
    )


def test_promising_subset_applies_exact_frozen_cut() -> None:
    subset = promising_subset(_frame())
    assert subset["source_id"].tolist() == ["1", "2"]


def test_validate_catalogue_rejects_count_drift() -> None:
    spec = CatalogueSpec("RGB", "x.csv", "0" * 32, 3)
    with pytest.raises(ValueError, match="count drift"):
        validate_catalogue(_frame(), spec)


def test_rank_is_deterministic_and_prefers_stronger_case() -> None:
    ranked = rank_promising_targets(_frame())
    assert ranked["source_id"].tolist() == ["2", "1"]
    assert ranked["priority_rank"].tolist() == [1, 2]
    assert ranked["followup_score"].between(0.0, 1.0).all()


def test_candidate_safe_summary_contains_no_identifiers() -> None:
    summary = candidate_safe_summary(rank_promising_targets(_frame()))
    text = str(summary)
    assert "source_id" not in text
    assert "ra" not in summary
    assert summary["rows"] == 2
    assert summary["population_counts"] == {"RGB": 2}
