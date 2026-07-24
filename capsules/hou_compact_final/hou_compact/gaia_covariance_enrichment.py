#!/usr/bin/env python3
"""Exact candidate enrichment for Gaia covariance fields.

Gaia ``corr_vec`` is a fixed-length array column and may arrive as a masked array. This
module serializes that array deterministically without ever asking NumPy to coerce an
array-valued mask to one boolean. Source-level rows remain inside the encrypted capsule.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from astropy.table import Table

_EXACT_ID = re.compile(r"^[0-9]{10,20}$")
_COVARIANCE_FIELDS = (
    "bit_index",
    "corr_vec",
    "center_of_mass_velocity",
    "center_of_mass_velocity_error",
    "t_periastron_error",
    "arg_periastron_error",
)


class GaiaCovarianceEnrichmentError(RuntimeError):
    """Raised when exact identity or Gaia array contracts fail closed."""


def _headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise GaiaCovarianceEnrichmentError("table has no header")
    result: dict[str, str] = {}
    for name in fieldnames:
        key = str(name).strip().lower().lstrip("\ufeff")
        if not key or key in result:
            raise GaiaCovarianceEnrichmentError(
                "table has empty or duplicate normalized header"
            )
        result[key] = str(name)
    return result


def _exact_id(value: object, *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not _EXACT_ID.fullmatch(token):
        raise GaiaCovarianceEnrichmentError(
            f"{label} is not an exact Gaia source identifier"
        )
    return token


def _scalar_or_array_text(value: object) -> str:
    """Serialize an Astropy scalar or masked array without ambiguous mask truth tests."""

    if isinstance(value, np.ma.MaskedArray):
        array = np.ma.asarray(value)
        if array.ndim == 0:
            if bool(np.ma.getmaskarray(array).item()):
                return ""
            return str(array.item())
        filled = np.asarray(array.filled(np.nan), dtype=float).reshape(-1)
        # Python's JSON NaN token is intentionally retained: the strict project decoder
        # maps it to an empty Gaia coefficient, and the DPAC reference receives a numeric
        # vector after canonical coercion.
        return json.dumps(
            filled.tolist(),
            separators=(",", ":"),
            allow_nan=True,
        )
    if np.ma.is_masked(value):
        return ""
    if isinstance(value, np.ndarray):
        array = np.asarray(value)
        if array.ndim == 0:
            return str(array.item())
        numeric = np.asarray(array, dtype=float).reshape(-1)
        return json.dumps(
            numeric.tolist(),
            separators=(",", ":"),
            allow_nan=True,
        )
    return str(value)


def _load_candidate_rows(
    path: Path,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        if "source_id" not in mapping:
            raise GaiaCovarianceEnrichmentError("candidate Gaia table lacks source_id")
        fields = list(reader.fieldnames or [])
        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            if None in row:
                raise GaiaCovarianceEnrichmentError(
                    "candidate Gaia row has extra fields"
                )
            source = _exact_id(
                row[mapping["source_id"]],
                label="candidate Gaia source",
            )
            if source in rows:
                raise GaiaCovarianceEnrichmentError(
                    "candidate Gaia table repeats a source"
                )
            rows[source] = row
    if not rows:
        raise GaiaCovarianceEnrichmentError("candidate Gaia table is empty")
    return fields, rows


def augment_candidate_covariance_fields(
    *,
    gaia_ecsv: Path,
    candidate_gaia: Path,
) -> dict[str, Any]:
    """Append exact Gaia covariance/reference fields without changing membership."""

    original_fields, rows = _load_candidate_rows(candidate_gaia)
    table = Table.read(gaia_ecsv, format="ascii.ecsv")
    available = {str(name).strip().lower(): str(name) for name in table.colnames}
    missing = sorted({"source_id", *_COVARIANCE_FIELDS} - set(available))
    if missing:
        raise GaiaCovarianceEnrichmentError(
            f"Gaia ECSV lacks covariance fields: {missing}"
        )

    source_records: dict[str, object] = {}
    for record in table:
        source = _exact_id(
            _scalar_or_array_text(record[available["source_id"]]),
            label="Gaia ECSV source",
        )
        if source not in rows:
            continue
        if source in source_records:
            raise GaiaCovarianceEnrichmentError(
                "Gaia ECSV repeats a candidate source"
            )
        source_records[source] = record
    if set(source_records) != set(rows):
        raise GaiaCovarianceEnrichmentError(
            "Gaia ECSV lacks one or more candidate sources"
        )

    normalized_existing = _headers(original_fields)
    appended = [
        name for name in _COVARIANCE_FIELDS if name not in normalized_existing
    ]
    fieldnames = original_fields + appended
    for source, row in rows.items():
        record = source_records[source]
        for name in appended:
            row[name] = _scalar_or_array_text(record[available[name]])

    temporary = candidate_gaia.with_suffix(
        candidate_gaia.suffix + ".covariance.tmp"
    )
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows.values())
    temporary.replace(candidate_gaia)

    return {
        "schema_version": "0.2",
        "candidate_safe": True,
        "candidate_sources": len(rows),
        "fields_appended": len(appended),
        "membership_preserved_exactly": True,
        "corr_vec_serialization": "flat JSON numeric array with NaN padding",
        "claim_boundary": (
            "Exact covariance-field enrichment only; no source is disclosed or re-ranked."
        ),
    }
