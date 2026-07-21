"""Gaia NSS correlation-vector decoding for SB1 and SB1C mass parameters.

The official Gaia DR3 data model stores the strict upper triangle of a correlation
matrix in column-major order. For SB1 the fitted-parameter order is period, systemic
velocity, K1, eccentricity, argument of periastron, and periastron epoch. For SB1C the
order is period, systemic velocity, K1, and the circular reference epoch.
"""

from __future__ import annotations

import ast
import math
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


@dataclass(frozen=True)
class MassParameterCovariance:
    """Covariance matrix for the orbital parameters entering the mass function."""

    parameter_names: tuple[str, ...]
    covariance: np.ndarray
    correlation: np.ndarray
    regularized: bool


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
    if value is None or np.ma.is_masked(value):
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def coerce_correlation_vector(values: object) -> np.ndarray:
    """Coerce array-like or common serialized array forms to a float vector."""
    if isinstance(values, str):
        text = values.strip()
        if not text:
            return np.array([], dtype=float)
        try:
            parsed = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            stripped = text.strip("[]()")
            tokens = stripped.replace(",", " ").split()
            return np.asarray([_coerce_scalar(token) for token in tokens], dtype=float)
        values = parsed
    if isinstance(values, np.ndarray):
        raw = values.ravel().tolist()
    elif isinstance(values, Sequence):
        raw = list(values)
    elif isinstance(values, Iterable):
        raw = list(values)
    else:
        raise TypeError("corr_vec must be array-like or a serialized array string")
    return np.asarray([_coerce_scalar(value) for value in raw], dtype=float)


def correlation_matrix_from_vector(values: object, n_parameters: int) -> np.ndarray:
    """Decode Gaia's strict upper-triangle correlation vector.

    Null, masked, and non-finite off-diagonal entries are interpreted as zero, matching
    Gaia's convention of serving only non-zero, non-unity correlation coefficients.
    """
    pairs = upper_triangle_column_major_pairs(n_parameters)
    vector = coerce_correlation_vector(values)
    if vector.size < len(pairs):
        raise ValueError(
            f"corr_vec has {vector.size} entries but {len(pairs)} are required"
        )
    matrix = np.eye(n_parameters, dtype=float)
    for value, (row, column) in zip(vector[: len(pairs)], pairs, strict=True):
        if abs(value) > 1.0 + 1e-7:
            raise ValueError(f"invalid correlation coefficient: {value}")
        clipped = float(np.clip(value, -1.0, 1.0))
        matrix[row, column] = clipped
        matrix[column, row] = clipped
    return matrix


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
    corr_vec: object,
    period_error: float,
    k1_error: float,
    eccentricity_error: float | None = None,
) -> MassParameterCovariance:
    """Extract the P/K1/e covariance block needed by the mass function."""
    solution = solution_type.strip()
    if solution == "SB1":
        full_order = SB1_PARAMETER_ORDER
        names = ("period", "semi_amplitude_primary", "eccentricity")
        indices = (0, 2, 3)
        errors = (period_error, k1_error, eccentricity_error)
    elif solution == "SB1C":
        full_order = SB1C_PARAMETER_ORDER
        names = ("period", "semi_amplitude_primary")
        indices = (0, 2)
        errors = (period_error, k1_error)
    else:
        raise ValueError(f"unsupported Gaia solution type: {solution_type!r}")

    numeric_errors: list[float] = []
    for name, value in zip(names, errors, strict=True):
        if value is None or not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"invalid uncertainty for {name}")
        numeric_errors.append(float(value))

    full_correlation = correlation_matrix_from_vector(corr_vec, len(full_order))
    correlation = full_correlation[np.ix_(indices, indices)]
    standard_errors = np.asarray(numeric_errors, dtype=float)
    covariance = correlation * standard_errors[:, None] * standard_errors[None, :]
    covariance, was_regularized = regularize_covariance(covariance)
    return MassParameterCovariance(
        parameter_names=names,
        covariance=covariance,
        correlation=correlation,
        regularized=was_regularized,
    )
