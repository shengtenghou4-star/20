"""Gaia DR3 NSS correlation-vector decoding for SB1 and SB1C mass parameters.

Gaia serves ``corr_vec`` as a fixed-length sparse array containing the strict upper
triangle of the applicable correlation matrix in column-major order. The official
``bit_index`` identifies the fitted parameter set. DPAC's public ``nsstools`` reference
implementation removes empty/zero padding before reconstructing the matrix. This module
supports that sparse representation, validates the SB1/SB1C bit index, and also accepts
compact vectors and explicit leading blocks for deterministic synthetic tests.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

SB1_PARAMETER_ORDER = (
    "period",
    "center_of_mass_velocity",
    "semi_amplitude_primary",
    "eccentricity",
    "arg_periastron",
    "t_periastron",
)
SB1C_PARAMETER_ORDER = (
    "period",
    "center_of_mass_velocity",
    "semi_amplitude_primary",
    "t_periastron",
)
EXPECTED_BIT_INDEX = {"SB1": 127, "SB1C": 31}


@dataclass(frozen=True)
class DecodedCorrelation:
    """One decoded model correlation matrix and its representation audit."""

    matrix: np.ndarray
    decoding_mode: str
    raw_vector_length: int
    coefficient_count: int


@dataclass(frozen=True)
class MassParameterCovariance:
    """Covariance matrix for the orbital parameters entering the mass function."""

    parameter_names: tuple[str, ...]
    covariance: np.ndarray
    correlation: np.ndarray
    regularized: bool
    bit_index: int
    decoding_mode: str
    raw_vector_length: int
    coefficient_count: int


def upper_triangle_column_major_pairs(n_parameters: int) -> tuple[tuple[int, int], ...]:
    """Return strict-upper-triangle indices in Gaia's documented storage order."""
    if not isinstance(n_parameters, int) or n_parameters < 1:
        raise ValueError("n_parameters must be a positive integer")
    return tuple(
        (row, column)
        for column in range(1, n_parameters)
        for row in range(column)
    )


def _coerce_scalar(value: object) -> float:
    """Return a float while preserving empty Gaia array elements as NaN."""
    if value is None or np.ma.is_masked(value):
        return math.nan
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "--", "nan", "none", "null", "masked"}:
            return math.nan
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def coerce_correlation_vector(values: object) -> np.ndarray:
    """Coerce an array or common ECSV/CSV serialization to a one-dimensional vector."""
    if isinstance(values, str):
        text = values.strip()
        if not text:
            return np.array([], dtype=float)
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            stripped = text.strip("[]()")
            tokens = [token for token in re.split(r"[,\s]+", stripped) if token]
            return np.asarray([_coerce_scalar(token) for token in tokens], dtype=float)
        values = parsed
    if isinstance(values, np.ma.MaskedArray):
        raw = values.filled(np.nan).ravel().tolist()
    elif isinstance(values, np.ndarray):
        raw = values.ravel().tolist()
    elif isinstance(values, Sequence):
        raw = list(values)
    elif isinstance(values, Iterable):
        raw = list(values)
    else:
        raise TypeError("corr_vec must be array-like or a serialized array string")
    return np.asarray([_coerce_scalar(value) for value in raw], dtype=float)


def validate_bit_index(solution_type: str, bit_index: object) -> int:
    """Validate the official fixed SB1/SB1C fitted-parameter mask."""
    solution = solution_type.strip()
    if solution not in EXPECTED_BIT_INDEX:
        raise ValueError(f"unsupported Gaia solution type: {solution_type!r}")
    if isinstance(bit_index, bool):
        raise TypeError("bit_index must be an integer")
    try:
        numeric = int(bit_index)
    except (TypeError, ValueError) as error:
        raise ValueError("bit_index must be an integer") from error
    expected = EXPECTED_BIT_INDEX[solution]
    if numeric != expected:
        raise ValueError(
            f"unexpected bit_index {numeric} for {solution}; expected {expected}"
        )
    return numeric


def _extract_model_coefficients(
    values: object,
    n_parameters: int,
) -> tuple[np.ndarray, str, int]:
    """Extract one model's upper-triangle coefficients from Gaia's sparse array.

    Preferred mode follows DPAC ``nsstools``: retain finite, non-zero entries in their
    original order. A compact vector is accepted directly. A fixed-length vector whose
    relevant coefficients occupy the leading block is also supported, which preserves
    explicitly represented zero correlations that the sparse filter cannot distinguish
    from padding.
    """
    pair_count = n_parameters * (n_parameters - 1) // 2
    raw = coerce_correlation_vector(values)
    if raw.size < pair_count:
        raise ValueError(
            f"corr_vec has {raw.size} entries but at least {pair_count} are required"
        )

    if raw.size == pair_count:
        coefficients = np.nan_to_num(raw, nan=0.0)
        return coefficients, "compact", int(raw.size)

    sparse = raw[np.isfinite(raw) & (raw != 0.0)]
    if sparse.size == pair_count:
        return sparse.astype(float, copy=False), "gaia_sparse_nonzero", int(raw.size)

    leading = raw[:pair_count]
    trailing = raw[pair_count:]
    trailing_is_padding = np.all(~np.isfinite(trailing) | (trailing == 0.0))
    if trailing_is_padding:
        coefficients = np.nan_to_num(leading, nan=0.0)
        return coefficients, "leading_block_with_padding", int(raw.size)

    raise ValueError(
        "corr_vec representation is ambiguous for the requested model: "
        f"raw_length={raw.size}, finite_nonzero={sparse.size}, expected={pair_count}"
    )


def decode_correlation_matrix(values: object, n_parameters: int) -> DecodedCorrelation:
    """Decode Gaia's strict upper-triangle correlation vector with an audit trail."""
    pairs = upper_triangle_column_major_pairs(n_parameters)
    coefficients, mode, raw_length = _extract_model_coefficients(values, n_parameters)
    matrix = np.eye(n_parameters, dtype=float)
    for value, (row, column) in zip(coefficients, pairs, strict=True):
        if not math.isfinite(float(value)) or abs(value) > 1.0 + 1e-7:
            raise ValueError(f"invalid correlation coefficient: {value}")
        clipped = float(np.clip(value, -1.0, 1.0))
        matrix[row, column] = clipped
        matrix[column, row] = clipped
    return DecodedCorrelation(
        matrix=matrix,
        decoding_mode=mode,
        raw_vector_length=raw_length,
        coefficient_count=len(coefficients),
    )


def correlation_matrix_from_vector(values: object, n_parameters: int) -> np.ndarray:
    """Compatibility wrapper returning only the decoded correlation matrix."""
    return decode_correlation_matrix(values, n_parameters).matrix


def regularize_covariance(
    covariance: np.ndarray,
    *,
    relative_floor: float = 1e-10,
) -> tuple[np.ndarray, bool]:
    """Return a symmetric positive-semidefinite covariance with original variances."""
    matrix = np.asarray(covariance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("covariance must be a square matrix")
    if np.any(~np.isfinite(matrix)):
        raise ValueError("covariance must be finite")
    diagonal = np.diag(matrix).copy()
    if np.any(diagonal < 0):
        raise ValueError("covariance diagonal must be non-negative")
    symmetric = 0.5 * (matrix + matrix.T)
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    scale = max(float(np.max(diagonal, initial=0.0)), 1.0)
    floor = relative_floor * scale
    if float(np.min(eigenvalues, initial=0.0)) >= -floor:
        return symmetric, False
    clipped = np.maximum(eigenvalues, floor)
    positive = (eigenvectors * clipped) @ eigenvectors.T
    new_diagonal = np.diag(positive)
    rescale = np.ones_like(diagonal)
    nonzero = (diagonal > 0) & (new_diagonal > 0)
    rescale[nonzero] = np.sqrt(diagonal[nonzero] / new_diagonal[nonzero])
    regularized = positive * rescale[:, None] * rescale[None, :]
    regularized[np.diag_indices_from(regularized)] = diagonal
    return 0.5 * (regularized + regularized.T), True


def sb1_mass_parameter_covariance(
    *,
    solution_type: str,
    bit_index: object,
    corr_vec: object,
    period_error: float,
    k1_error: float,
    eccentricity_error: float | None = None,
) -> MassParameterCovariance:
    """Extract the validated P/K1/e covariance block needed by the mass function."""
    solution = solution_type.strip()
    validated_bit_index = validate_bit_index(solution, bit_index)
    if solution == "SB1":
        full_order = SB1_PARAMETER_ORDER
        names = ("period", "semi_amplitude_primary", "eccentricity")
        indices = (0, 2, 3)
        errors = (period_error, k1_error, eccentricity_error)
    else:
        full_order = SB1C_PARAMETER_ORDER
        names = ("period", "semi_amplitude_primary")
        indices = (0, 2)
        errors = (period_error, k1_error)

    numeric_errors: list[float] = []
    for name, value in zip(names, errors, strict=True):
        if value is None or not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"invalid uncertainty for {name}")
        numeric_errors.append(float(value))

    decoded = decode_correlation_matrix(corr_vec, len(full_order))
    correlation = decoded.matrix[np.ix_(indices, indices)]
    standard_errors = np.asarray(numeric_errors, dtype=float)
    covariance = correlation * standard_errors[:, None] * standard_errors[None, :]
    covariance, was_regularized = regularize_covariance(covariance)
    return MassParameterCovariance(
        parameter_names=names,
        covariance=covariance,
        correlation=correlation,
        regularized=was_regularized,
        bit_index=validated_bit_index,
        decoding_mode=decoded.decoding_mode,
        raw_vector_length=decoded.raw_vector_length,
        coefficient_count=decoded.coefficient_count,
    )
