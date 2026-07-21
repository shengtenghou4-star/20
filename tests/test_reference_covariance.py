import sys
from types import SimpleNamespace

import numpy as np
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


def test_covariance_to_correlation() -> None:
    covariance = np.array([[4.0, 3.0], [3.0, 9.0]])
    correlation = covariance_to_correlation(covariance)
    assert np.allclose(correlation, [[1.0, 0.5], [0.5, 1.0]])


def test_compare_with_fake_dpac_reference(monkeypatch: pytest.MonkeyPatch) -> None:
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

    fake = SimpleNamespace(
        get_field_names=lambda row: list(names),
        make_covmat=lambda row: covariance,
    )
    monkeypatch.setitem(sys.modules, "nsstools", fake)
    row = {
        "nss_solution_type": "SB1",
        "bit_index": 127,
        "corr_vec": fixed,
    }
    comparison = compare_with_nsstools(row)
    assert comparison.maximum_absolute_difference == pytest.approx(0.0, abs=1e-15)
    assert comparison.decoding_mode == "gaia_sparse_nonzero"
    assert comparison.parameter_names == names


def test_reference_field_order_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = SimpleNamespace(
        get_field_names=lambda row: ["period", "semi_amplitude_primary"],
        make_covmat=lambda row: np.eye(2),
    )
    monkeypatch.setitem(sys.modules, "nsstools", fake)
    with pytest.raises(ValueError, match="field order differs"):
        compare_with_nsstools(
            {
                "nss_solution_type": "SB1C",
                "bit_index": 31,
                "corr_vec": np.zeros(6),
            }
        )


def test_missing_reference_package_has_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "nsstools", raising=False)

    def fail_import(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr("hou_compact.reference_covariance.importlib.import_module", fail_import)
    with pytest.raises(RuntimeError, match="hou-compact\[reference\]"):
        compare_with_nsstools(
            {
                "nss_solution_type": "SB1C",
                "bit_index": 31,
                "corr_vec": np.zeros(6),
            }
        )
