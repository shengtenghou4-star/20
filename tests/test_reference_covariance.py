import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hou_compact.reference_covariance import (
    compare_with_nsstools,
    covariance_to_correlation,
)


def _compact_to_matrix(values: np.ndarray, n_parameters: int) -> np.ndarray:
    matrix = np.eye(n_parameters)
    index = 0
    for column in range(1, n_parameters):
        for row in range(column):
            matrix[row, column] = values[index]
            matrix[column, row] = values[index]
            index += 1
    return matrix


def _sb1_row(corr_vec: object) -> dict[str, object]:
    return {
        "source_id": 123,
        "nss_solution_type": "SB1",
        "bit_index": 127,
        "corr_vec": corr_vec,
        "period": 10.0,
        "period_error": 2.0,
        "center_of_mass_velocity": 20.0,
        "center_of_mass_velocity_error": 3.0,
        "semi_amplitude_primary": 30.0,
        "semi_amplitude_primary_error": 4.0,
        "eccentricity": 0.2,
        "eccentricity_error": 0.1,
        "arg_periastron": 45.0,
        "arg_periastron_error": 5.0,
        "t_periastron": 100.0,
        "t_periastron_error": 6.0,
    }


def test_covariance_to_correlation() -> None:
    covariance = np.array([[4.0, 3.0], [3.0, 9.0]])
    correlation = covariance_to_correlation(covariance)
    assert np.allclose(correlation, [[1.0, 0.5], [0.5, 1.0]])


def test_compare_with_fake_official_nsssource(monkeypatch: pytest.MonkeyPatch) -> None:
    coefficients = np.linspace(0.01, 0.15, 15)
    fixed = np.full(231, np.nan)
    fixed[np.linspace(0, 230, 15, dtype=int)] = coefficients
    names = (
        "period",
        "center_of_mass_velocity",
        "semi_amplitude_primary",
        "eccentricity",
        "arg_periastron",
        "t_periastron",
    )
    errors = np.array([2.0, 3.0, 4.0, 0.1, 5.0, 6.0])
    correlation = _compact_to_matrix(coefficients, 6)
    covariance = correlation * errors[:, None] * errors[None, :]

    class FakeNssSource:
        def __init__(self, frame: pd.DataFrame, indice: int = 0) -> None:
            assert indice == 0
            source = frame.iloc[0]
            assert np.isnan(source["ra_error"])
            assert source["period_error"] == 2.0
            self.frame = frame

        def covmat(self) -> pd.DataFrame:
            return pd.DataFrame(covariance, index=names, columns=names)

    monkeypatch.setitem(sys.modules, "nsstools", SimpleNamespace(NssSource=FakeNssSource))
    comparison = compare_with_nsstools(_sb1_row(fixed))
    assert comparison.maximum_absolute_difference == pytest.approx(0.0, abs=1e-15)
    assert comparison.decoding_mode == "gaia_sparse_nonzero"
    assert comparison.parameter_names == names
    assert comparison.reference_api == "nsstools.NssSource.covmat"


def test_sb1c_frame_activates_only_circular_solution_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coefficients = np.linspace(0.01, 0.06, 6)
    correlation = _compact_to_matrix(coefficients, 4)
    names = (
        "period",
        "center_of_mass_velocity",
        "semi_amplitude_primary",
        "t_periastron",
    )
    errors = np.array([1.0, 2.0, 3.0, 4.0])
    covariance = correlation * errors[:, None] * errors[None, :]

    class FakeNssSource:
        def __init__(self, frame: pd.DataFrame, indice: int = 0) -> None:
            source = frame.iloc[indice]
            assert np.isnan(source["eccentricity_error"])
            assert np.isnan(source["arg_periastron_error"])
            assert source["t_periastron_error"] == 4.0

        def covmat(self) -> pd.DataFrame:
            return pd.DataFrame(covariance, index=names, columns=names)

    monkeypatch.setitem(sys.modules, "nsstools", SimpleNamespace(NssSource=FakeNssSource))
    comparison = compare_with_nsstools(
        {
            "source_id": 456,
            "nss_solution_type": "SB1C",
            "bit_index": 31,
            "corr_vec": coefficients,
            "period": 5.0,
            "period_error": 1.0,
            "center_of_mass_velocity": 10.0,
            "center_of_mass_velocity_error": 2.0,
            "semi_amplitude_primary": 20.0,
            "semi_amplitude_primary_error": 3.0,
            "t_periastron": 50.0,
            "t_periastron_error": 4.0,
        }
    )
    assert comparison.maximum_absolute_difference == pytest.approx(0.0, abs=1e-15)
    assert comparison.parameter_names == names


def test_reference_field_order_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNssSource:
        def __init__(self, frame: pd.DataFrame, indice: int = 0) -> None:
            pass

        def covmat(self) -> pd.DataFrame:
            names = ["period", "semi_amplitude_primary", "center_of_mass_velocity", "t_periastron"]
            return pd.DataFrame(np.eye(4), index=names, columns=names)

    monkeypatch.setitem(sys.modules, "nsstools", SimpleNamespace(NssSource=FakeNssSource))
    with pytest.raises(ValueError, match="field order differs"):
        compare_with_nsstools(
            {
                "nss_solution_type": "SB1C",
                "bit_index": 31,
                "corr_vec": np.linspace(0.01, 0.06, 6),
                "period_error": 1.0,
                "center_of_mass_velocity_error": 1.0,
                "semi_amplitude_primary_error": 1.0,
                "t_periastron_error": 1.0,
            }
        )


def test_missing_required_uncertainty_fails_before_reference_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "nsstools",
        SimpleNamespace(NssSource=lambda frame, indice=0: None),
    )
    row = _sb1_row(np.linspace(0.01, 0.15, 15))
    row["period_error"] = None
    with pytest.raises(ValueError, match="missing finite uncertainties"):
        compare_with_nsstools(row)


def test_missing_reference_package_has_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "nsstools", raising=False)

    def fail_import(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr("hou_compact.reference_covariance.importlib.import_module", fail_import)
    with pytest.raises(RuntimeError, match=r"hou-compact\[reference\]"):
        compare_with_nsstools(
            {
                "nss_solution_type": "SB1C",
                "bit_index": 31,
                "corr_vec": np.linspace(0.01, 0.06, 6),
            }
        )
