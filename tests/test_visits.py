import math

import pandas as pd
import pytest

from hou_compact.visits import aggregate_independent_visits


def test_close_exposures_are_combined_by_inverse_variance() -> None:
    rows = pd.DataFrame(
        {
            "source_id": [1, 1],
            "mjd": [59000.0, 59000.01],
            "vrad": [10.0, 14.0],
            "vrad_err": [1.0, 2.0],
            "night": [20200101, 20200101],
            "survey": ["main", "main"],
            "program": ["bright", "bright"],
        }
    )
    visits = aggregate_independent_visits(rows, maximum_gap_hours=2.0)
    assert len(visits) == 1
    assert visits.loc[0, "vrad"] == pytest.approx(10.8)
    assert visits.loc[0, "n_exposures"] == 2
    assert visits.loc[0, "visit_span_hours"] == pytest.approx(0.24)
    assert visits.loc[0, "error_inflation_factor"] > 1.0


def test_large_time_gap_creates_two_visits_on_same_night() -> None:
    rows = pd.DataFrame(
        {
            "source_id": [1, 1],
            "mjd": [59000.0, 59000.2],
            "vrad": [10.0, 20.0],
            "vrad_err": [1.0, 1.0],
            "night": [20200101, 20200101],
        }
    )
    visits = aggregate_independent_visits(rows, maximum_gap_hours=2.0)
    assert len(visits) == 2


def test_night_change_creates_new_visit_even_for_small_gap() -> None:
    rows = pd.DataFrame(
        {
            "source_id": [1, 1],
            "mjd": [59000.99, 59001.0],
            "vrad": [10.0, 11.0],
            "vrad_err": [1.0, 1.0],
            "night": [20200101, 20200102],
        }
    )
    visits = aggregate_independent_visits(rows, maximum_gap_hours=2.0)
    assert len(visits) == 2


def test_source_change_never_merges_visits() -> None:
    rows = pd.DataFrame(
        {
            "source_id": [1, 2],
            "mjd": [59000.0, 59000.0],
            "vrad": [10.0, 10.0],
            "vrad_err": [1.0, 1.0],
        }
    )
    visits = aggregate_independent_visits(rows)
    assert len(visits) == 2
    assert visits["source_id"].tolist() == [1, 2]


def test_error_floor_is_added_in_quadrature() -> None:
    rows = pd.DataFrame(
        {
            "source_id": [1],
            "mjd": [59000.0],
            "vrad": [10.0],
            "vrad_err": [1.0],
        }
    )
    visits = aggregate_independent_visits(rows, error_floor_kms=2.0)
    assert visits.loc[0, "vrad_err"] == pytest.approx(math.sqrt(5.0))


def test_invalid_errors_are_rejected() -> None:
    rows = pd.DataFrame(
        {
            "source_id": [1],
            "mjd": [59000.0],
            "vrad": [10.0],
            "vrad_err": [0.0],
        }
    )
    with pytest.raises(ValueError, match="positive"):
        aggregate_independent_visits(rows)
