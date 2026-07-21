import numpy as np
import pytest

from hou_compact.gaia_covariance import (
    correlation_matrix_from_vector,
    regularize_covariance,
    sb1_mass_parameter_covariance,
    upper_triangle_column_major_pairs,
)


def test_upper_triangle_column_major_order() -> None:
    assert upper_triangle_column_major_pairs(4) == (
        (0, 1),
        (0, 2),
        (1, 2),
        (0, 3),
        (1, 3),
        (2, 3),
    )


def test_decode_known_four_parameter_vector() -> None:
    matrix = correlation_matrix_from_vector([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], 4)
    expected = np.array(
        [
            [1.0, 0.1, 0.2, 0.4],
            [0.1, 1.0, 0.3, 0.5],
            [0.2, 0.3, 1.0, 0.6],
            [0.4, 0.5, 0.6, 1.0],
        ]
    )
    assert np.allclose(matrix, expected)


def test_null_serialized_entries_become_zero() -> None:
    matrix = correlation_matrix_from_vector("[0.1, nan, --, 0.0, 0.2, 0.3]", 4)
    assert matrix[0, 1] == pytest.approx(0.1)
    assert matrix[0, 2] == pytest.approx(0.0)
    assert matrix[1, 2] == pytest.approx(0.0)


def test_sb1_mass_covariance_selects_period_k1_eccentricity() -> None:
    vector = np.zeros(15)
    vector[1] = 0.25  # corr(period, K1)
    vector[3] = -0.10  # corr(period, eccentricity)
    vector[5] = 0.40  # corr(K1, eccentricity)
    result = sb1_mass_parameter_covariance(
        solution_type="SB1",
        corr_vec=vector,
        period_error=2.0,
        k1_error=3.0,
        eccentricity_error=0.1,
    )
    assert result.parameter_names == (
        "period",
        "semi_amplitude_primary",
        "eccentricity",
    )
    assert result.covariance[0, 1] == pytest.approx(0.25 * 2.0 * 3.0)
    assert result.covariance[0, 2] == pytest.approx(-0.10 * 2.0 * 0.1)
    assert result.covariance[1, 2] == pytest.approx(0.40 * 3.0 * 0.1)


def test_sb1c_mass_covariance_is_two_dimensional() -> None:
    vector = np.zeros(6)
    vector[1] = -0.5  # corr(period, K1) in four-parameter order
    result = sb1_mass_parameter_covariance(
        solution_type="SB1C",
        corr_vec=vector,
        period_error=1.0,
        k1_error=4.0,
    )
    assert result.parameter_names == ("period", "semi_amplitude_primary")
    assert result.covariance.shape == (2, 2)
    assert result.covariance[0, 1] == pytest.approx(-2.0)


def test_regularize_indefinite_covariance() -> None:
    covariance = np.array([[1.0, 2.0], [2.0, 1.0]])
    fixed, changed = regularize_covariance(covariance)
    assert changed is True
    assert np.min(np.linalg.eigvalsh(fixed)) >= -1e-9
    assert np.allclose(np.diag(fixed), [1.0, 1.0])
