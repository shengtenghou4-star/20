import numpy as np
import pytest

from hou_compact.gaia_covariance import (
    correlation_matrix_from_vector,
    decode_correlation_matrix,
    regularize_covariance,
    sb1_mass_parameter_covariance,
    upper_triangle_column_major_pairs,
    validate_bit_index,
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


def test_decode_known_four_parameter_compact_vector() -> None:
    decoded = decode_correlation_matrix([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], 4)
    expected = np.array(
        [
            [1.0, 0.1, 0.2, 0.4],
            [0.1, 1.0, 0.3, 0.5],
            [0.2, 0.3, 1.0, 0.6],
            [0.4, 0.5, 0.6, 1.0],
        ]
    )
    assert np.allclose(decoded.matrix, expected)
    assert decoded.decoding_mode == "compact"
    assert decoded.raw_vector_length == 6


def test_null_serialized_entries_become_zero_in_compact_vector() -> None:
    matrix = correlation_matrix_from_vector("[0.1, nan, --, 0.0, 0.2, 0.3]", 4)
    assert matrix[0, 1] == pytest.approx(0.1)
    assert matrix[0, 2] == pytest.approx(0.0)
    assert matrix[1, 2] == pytest.approx(0.0)


def test_fixed_length_sparse_vector_matches_dpac_nonzero_compaction() -> None:
    compact = np.array([0.11, 0.22, 0.33, 0.44, 0.55, 0.66])
    fixed = np.full(231, np.nan)
    fixed[[0, 4, 9, 20, 80, 200]] = compact
    decoded = decode_correlation_matrix(fixed, 4)
    expected = correlation_matrix_from_vector(compact, 4)
    assert np.allclose(decoded.matrix, expected)
    assert decoded.decoding_mode == "gaia_sparse_nonzero"
    assert decoded.raw_vector_length == 231
    assert decoded.coefficient_count == 6


def test_leading_block_preserves_explicit_zero_correlation() -> None:
    fixed = np.full(231, np.nan)
    fixed[:6] = [0.1, 0.0, 0.3, 0.4, 0.5, 0.6]
    decoded = decode_correlation_matrix(fixed, 4)
    assert decoded.decoding_mode == "leading_block_with_padding"
    assert decoded.matrix[0, 2] == pytest.approx(0.0)
    assert decoded.matrix[1, 2] == pytest.approx(0.3)


def test_sb1_mass_covariance_selects_period_k1_eccentricity() -> None:
    vector = np.zeros(15)
    vector[1] = 0.25  # corr(period, K1)
    vector[3] = -0.10  # corr(period, eccentricity)
    vector[5] = 0.40  # corr(K1, eccentricity)
    result = sb1_mass_parameter_covariance(
        solution_type="SB1",
        bit_index=127,
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
    assert result.bit_index == 127
    assert result.covariance[0, 1] == pytest.approx(0.25 * 2.0 * 3.0)
    assert result.covariance[0, 2] == pytest.approx(-0.10 * 2.0 * 0.1)
    assert result.covariance[1, 2] == pytest.approx(0.40 * 3.0 * 0.1)


def test_sb1c_mass_covariance_is_two_dimensional() -> None:
    vector = np.zeros(6)
    vector[1] = -0.5  # corr(period, K1) in four-parameter order
    result = sb1_mass_parameter_covariance(
        solution_type="SB1C",
        bit_index=31,
        corr_vec=vector,
        period_error=1.0,
        k1_error=4.0,
    )
    assert result.parameter_names == ("period", "semi_amplitude_primary")
    assert result.covariance.shape == (2, 2)
    assert result.covariance[0, 1] == pytest.approx(-2.0)


def test_wrong_bit_index_is_rejected() -> None:
    with pytest.raises(ValueError, match="unexpected bit_index"):
        validate_bit_index("SB1", 31)
    with pytest.raises(ValueError, match="unexpected bit_index"):
        sb1_mass_parameter_covariance(
            solution_type="SB1C",
            bit_index=127,
            corr_vec=np.zeros(6),
            period_error=1.0,
            k1_error=1.0,
        )


def test_ambiguous_fixed_length_vector_is_rejected() -> None:
    fixed = np.full(231, np.nan)
    fixed[:5] = [0.1, 0.2, 0.3, 0.4, 0.5]
    fixed[100] = 0.8
    fixed[150] = -0.7
    with pytest.raises(ValueError, match="ambiguous"):
        decode_correlation_matrix(fixed, 4)


def test_regularize_indefinite_covariance() -> None:
    covariance = np.array([[1.0, 2.0], [2.0, 1.0]])
    fixed, changed = regularize_covariance(covariance)
    assert changed is True
    assert np.min(np.linalg.eigvalsh(fixed)) >= -1e-9
    assert np.allclose(np.diag(fixed), [1.0, 1.0])
