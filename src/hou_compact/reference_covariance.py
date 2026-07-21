"""Independent parity checks against the public Gaia DPAC ``nsstools`` package.

This module is intentionally optional. Scientific production uses HOU-COMPACT's strict
bit-index decoder, while a live-row audit can install ``hou-compact[reference]`` and
compare the reconstructed covariance matrix with DPAC's independently maintained
``nsstools.make_covmat`` implementation.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from hou_compact.gaia_covariance import (
    SB1C_PARAMETER_ORDER,
    SB1_PARAMETER_ORDER,
    decode_correlation_matrix,
    validate_bit_index,
)


@dataclass(frozen=True)
class ReferenceCovarianceComparison:
    """Result of comparing one live Gaia row with the DPAC reference tool."""

    parameter_names: tuple[str, ...]
    hou_correlation: np.ndarray
    reference_correlation: np.ndarray
    maximum_absolute_difference: float
    decoding_mode: str
    raw_vector_length: int
    coefficient_count: int


def _parameter_order(solution_type: str) -> tuple[str, ...]:
    solution = solution_type.strip()
    if solution == "SB1":
        return SB1_PARAMETER_ORDER
    if solution == "SB1C":
        return SB1C_PARAMETER_ORDER
    raise ValueError(f"unsupported Gaia solution type: {solution_type!r}")


def covariance_to_correlation(covariance: np.ndarray) -> np.ndarray:
    """Convert a finite covariance matrix to a correlation matrix."""
    matrix = np.asarray(covariance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("covariance must be a square matrix")
    if np.any(~np.isfinite(matrix)):
        raise ValueError("covariance must be finite")
    diagonal = np.diag(matrix)
    if np.any(diagonal <= 0):
        raise ValueError("reference covariance variances must be positive")
    scale = np.sqrt(diagonal)
    correlation = matrix / scale[:, None] / scale[None, :]
    correlation[np.diag_indices_from(correlation)] = 1.0
    return 0.5 * (correlation + correlation.T)


def compare_with_nsstools(row: Mapping[str, object]) -> ReferenceCovarianceComparison:
    """Compare one Gaia row against ``nsstools`` and fail on field-order mismatch."""
    solution_type = str(row.get("nss_solution_type", "")).strip()
    parameter_names = _parameter_order(solution_type)
    validate_bit_index(solution_type, row.get("bit_index"))
    decoded = decode_correlation_matrix(row.get("corr_vec"), len(parameter_names))

    try:
        nsstools = importlib.import_module("nsstools")
    except ImportError as error:
        raise RuntimeError(
            "nsstools is required for the reference audit; install hou-compact[reference]"
        ) from error

    series = pd.Series(dict(row))
    reference_names = tuple(nsstools.get_field_names(series))
    if reference_names != parameter_names:
        raise ValueError(
            "DPAC reference field order differs from the expected Gaia solution order: "
            f"reference={reference_names}, expected={parameter_names}"
        )
    reference_covariance = np.asarray(nsstools.make_covmat(series), dtype=float)
    reference_correlation = covariance_to_correlation(reference_covariance)
    if reference_correlation.shape != decoded.matrix.shape:
        raise ValueError(
            "DPAC reference matrix shape differs from HOU-COMPACT decode: "
            f"reference={reference_correlation.shape}, hou={decoded.matrix.shape}"
        )
    difference = float(np.max(np.abs(reference_correlation - decoded.matrix), initial=0.0))
    if not math.isfinite(difference):
        raise ValueError("non-finite covariance parity difference")
    return ReferenceCovarianceComparison(
        parameter_names=parameter_names,
        hou_correlation=decoded.matrix,
        reference_correlation=reference_correlation,
        maximum_absolute_difference=difference,
        decoding_mode=decoded.decoding_mode,
        raw_vector_length=decoded.raw_vector_length,
        coefficient_count=decoded.coefficient_count,
    )
