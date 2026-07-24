"""Independent parity checks against the public Gaia DPAC ``nsstools`` package.

This module is intentionally optional. Scientific production uses HOU-COMPACT's strict
bit-index decoder, while a live-row audit can install ``hou-compact[reference]`` and
compare the reconstructed covariance matrix with DPAC's independently maintained
``NssSource.covmat`` implementation.
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
    coerce_correlation_vector,
    decode_correlation_matrix,
    validate_bit_index,
)

_NSSTOOLS_BASE_FIELDS = (
    "ra",
    "dec",
    "parallax",
    "pmra",
    "pmdec",
    "a_thiele_innes",
    "b_thiele_innes",
    "f_thiele_innes",
    "g_thiele_innes",
    "c_thiele_innes",
    "h_thiele_innes",
)
_NSSTOOLS_SB_FIELDS = (
    "period",
    "center_of_mass_velocity",
    "semi_amplitude_primary",
    "semi_amplitude_secondary",
    "eccentricity",
    "arg_periastron",
    "t_periastron",
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
    reference_api: str


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


def _finite_or_nan(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return numeric if math.isfinite(numeric) else float("nan")


def _nsstools_frame(
    row: Mapping[str, object],
    parameter_names: tuple[str, ...],
) -> pd.DataFrame:
    """Build the complete one-row schema expected by nsstools 0.1.12.

    ``NssSource`` derives its active field order from finite ``*_error`` columns. Gaia SB1C
    rows therefore receive finite period/gamma/K1/epoch uncertainties and NaN eccentricity
    and omega uncertainties; all astrometric and secondary-amplitude fields are explicitly
    inactive. This keeps the independent package's own ordering logic authoritative.

    Candidate relay CSV files serialize Gaia's array-valued ``corr_vec`` as text. It is
    canonicalized back to a numeric vector here so the DPAC package never receives a Python
    string whose characters could be mistaken for correlation entries.
    """

    payload: dict[str, object] = {
        "source_id": row.get("source_id", -1),
        "nss_solution_type": row.get("nss_solution_type"),
        "corr_vec": coerce_correlation_vector(row.get("corr_vec")),
    }
    all_fields = (*_NSSTOOLS_BASE_FIELDS, *_NSSTOOLS_SB_FIELDS)
    active = set(parameter_names)
    for field in all_fields:
        payload[field] = _finite_or_nan(row.get(field))
        error_name = f"{field}_error"
        payload[error_name] = (
            _finite_or_nan(row.get(error_name)) if field in active else float("nan")
        )
    missing_errors = [
        name for name in parameter_names if not math.isfinite(payload[f"{name}_error"])
    ]
    if missing_errors:
        raise ValueError(
            "live Gaia row is missing finite uncertainties required by nsstools: "
            f"{missing_errors}"
        )
    return pd.DataFrame([payload])


def compare_with_nsstools(row: Mapping[str, object]) -> ReferenceCovarianceComparison:
    """Compare one Gaia row against ``NssSource.covmat`` and fail on order mismatch."""

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
    nss_source = getattr(nsstools, "NssSource", None)
    if nss_source is None:
        raise RuntimeError("installed nsstools package does not expose NssSource")

    frame = _nsstools_frame(row, parameter_names)
    reference_frame = nss_source(frame, indice=0).covmat()
    if not isinstance(reference_frame, pd.DataFrame):
        raise TypeError("nsstools NssSource.covmat() did not return a pandas DataFrame")
    reference_names = tuple(str(name) for name in reference_frame.index)
    reference_columns = tuple(str(name) for name in reference_frame.columns)
    if reference_names != reference_columns:
        raise ValueError(
            "DPAC reference covariance row and column orders differ: "
            f"rows={reference_names}, columns={reference_columns}"
        )
    if reference_names != parameter_names:
        raise ValueError(
            "DPAC reference field order differs from the expected Gaia solution order: "
            f"reference={reference_names}, expected={parameter_names}"
        )
    reference_covariance = reference_frame.to_numpy(dtype=float)
    reference_correlation = covariance_to_correlation(reference_covariance)
    if reference_correlation.shape != decoded.matrix.shape:
        raise ValueError(
            "DPAC reference matrix shape differs from HOU-COMPACT decode: "
            f"reference={reference_correlation.shape}, hou={decoded.matrix.shape}"
        )
    difference = float(
        np.max(np.abs(reference_correlation - decoded.matrix), initial=0.0)
    )
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
        reference_api="nsstools.NssSource.covmat",
    )
