"""Exact Gaia DR3 access to LAMOST DR8 v2.0 AFGK per-spectrum RV rows.

DR8 v2.0 publishes the Gaia DR3 identifier as a character field in its
per-spectrum catalogues.  This module therefore queries the documented ``stellar``
table directly by exact Gaia DR3 text, avoiding the lossy DR8 v1.0 float identity
field and the unnecessary DR3-to-DR2 multiple-epoch bridge.

Returned rows are standardized into the common HOU-COMPACT epoch schema.  They
remain source-level research data and must be encrypted before persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd

from hou_compact.lamost import parse_exact_int_text

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LamostDR3SpectrumError(RuntimeError):
    """Raised when exact DR3 per-spectrum retrieval violates the frozen contract."""


@dataclass(frozen=True)
class DR3SpectrumSpec:
    """Frozen public DR8 v2.0 AFGK spectrum contract."""

    table_name: str = "stellar"
    gaia_source_id_column: str = "gaia_source_id"
    obsid_column: str = "obsid"
    mjd_column: str = "mjd"
    rv_column: str = "rv"
    rv_error_column: str = "rv_err"
    sn_g_column: str = "snrg"
    sn_i_column: str = "snri"
    sn_z_column: str = "snrz"
    fibermask_column: str = "fibermask"
    class_column: str = "class"
    subclass_column: str = "subclass"

    def __post_init__(self) -> None:
        for value in self.selected_columns:
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"unsafe SQL identifier: {value!r}")
        if not _IDENTIFIER.fullmatch(self.table_name):
            raise ValueError(f"unsafe SQL table identifier: {self.table_name!r}")

    @property
    def selected_columns(self) -> tuple[str, ...]:
        return (
            self.gaia_source_id_column,
            self.obsid_column,
            self.mjd_column,
            self.rv_column,
            self.rv_error_column,
            self.sn_g_column,
            self.sn_i_column,
            self.sn_z_column,
            self.fibermask_column,
            self.class_column,
            self.subclass_column,
        )

    def to_record(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DR3SpectrumQueryReceipt:
    table_name: str
    batch_index: int
    input_source_count: int
    returned_row_count: int
    query_sha256: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def normalize_dr3_source_ids(values: Iterable[object]) -> list[int]:
    """Return sorted unique exact Gaia DR3 identifiers."""

    normalized = {
        parse_exact_int_text(value, name="gaia_dr3_source_id") for value in values
    }
    if any(value < 0 for value in normalized):
        raise ValueError("Gaia DR3 source IDs must be non-negative")
    return sorted(normalized)


def _chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def build_exact_dr3_spectrum_query(
    spec: DR3SpectrumSpec,
    source_ids: list[int],
) -> str:
    """Build a bounded exact-character Gaia DR3 query."""

    if not source_ids:
        raise ValueError("source_ids must not be empty")
    if source_ids != sorted(set(source_ids)):
        raise ValueError("source_ids must be sorted and unique")
    literals = ", ".join(f"'{value}'" for value in source_ids)
    columns = ", ".join(spec.selected_columns)
    return (
        f"SELECT {columns} FROM {spec.table_name} "
        f"WHERE {spec.gaia_source_id_column} IN ({literals})"
    )


def build_contract_probe_query(spec: DR3SpectrumSpec = DR3SpectrumSpec()) -> str:
    """Return a source-free query that validates the frozen table contract."""

    columns = ", ".join(spec.selected_columns)
    return f"SELECT {columns} FROM {spec.table_name} WHERE 1 = 0"


def _standardize_rows(
    frame: pd.DataFrame,
    spec: DR3SpectrumSpec,
    target_ids: set[int],
) -> pd.DataFrame:
    output_columns = [
        "source_id",
        "obsid",
        "expid",
        "mjd",
        "vrad",
        "vrad_err",
        "success",
        "rvs_warn",
        "fiberstatus",
        "sn_b",
        "sn_r",
        "sn_z",
        "survey",
        "program",
        "source_match_mode",
        "class",
        "subclass",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)

    lowered = {str(column).lower(): str(column) for column in frame.columns}
    missing = [column for column in spec.selected_columns if column.lower() not in lowered]
    if missing:
        raise LamostDR3SpectrumError(
            f"{spec.table_name} result missing frozen columns: {sorted(missing)}"
        )

    source = pd.Series(
        [
            parse_exact_int_text(value, name="lamost.gaia_source_id")
            for value in frame[lowered[spec.gaia_source_id_column.lower()]]
        ],
        index=frame.index,
        dtype="int64",
    )
    if not set(source).issubset(target_ids):
        raise LamostDR3SpectrumError(
            "LAMOST returned Gaia DR3 identifiers outside the exact query"
        )

    obsid = pd.to_numeric(
        frame[lowered[spec.obsid_column.lower()]], errors="raise"
    ).astype("int64")
    if obsid.duplicated().any():
        raise LamostDR3SpectrumError(
            f"LAMOST returned {int(obsid.duplicated().sum())} duplicate obsid rows"
        )

    mjd = pd.to_numeric(frame[lowered[spec.mjd_column.lower()]], errors="coerce")
    rv = pd.to_numeric(frame[lowered[spec.rv_column.lower()]], errors="coerce")
    rv_error = pd.to_numeric(
        frame[lowered[spec.rv_error_column.lower()]], errors="coerce"
    )
    fiber = pd.to_numeric(
        frame[lowered[spec.fibermask_column.lower()]], errors="coerce"
    )
    fiberstatus = fiber.fillna(1).astype("int64")
    finite = np.isfinite(mjd) & np.isfinite(rv) & np.isfinite(rv_error)
    success = finite & rv_error.gt(0) & fiberstatus.eq(0)

    standardized = pd.DataFrame(
        {
            "source_id": source,
            "obsid": obsid,
            "expid": obsid,
            "mjd": mjd,
            "vrad": rv,
            "vrad_err": rv_error,
            "success": success.astype(bool),
            "rvs_warn": np.where(success, 0, 1).astype("int64"),
            "fiberstatus": fiberstatus,
            "sn_b": pd.to_numeric(
                frame[lowered[spec.sn_g_column.lower()]], errors="coerce"
            ),
            "sn_r": pd.to_numeric(
                frame[lowered[spec.sn_i_column.lower()]], errors="coerce"
            ),
            "sn_z": pd.to_numeric(
                frame[lowered[spec.sn_z_column.lower()]], errors="coerce"
            ),
            "survey": "lamost_dr8_v2",
            "program": spec.table_name,
            "source_match_mode": "exact_gaia_dr3_character_id",
            "class": frame[lowered[spec.class_column.lower()]].astype("string"),
            "subclass": frame[lowered[spec.subclass_column.lower()]].astype("string"),
        }
    )
    return standardized.loc[:, output_columns].sort_values(
        ["source_id", "mjd", "obsid"], kind="stable"
    ).reset_index(drop=True)


def query_exact_dr3_spectra(
    service: Any,
    source_ids: Iterable[object],
    *,
    spec: DR3SpectrumSpec = DR3SpectrumSpec(),
    batch_size: int = 25,
    maxrec_per_batch: int = 5_000,
) -> tuple[pd.DataFrame, list[DR3SpectrumQueryReceipt]]:
    """Query exact DR3 IDs and return standardized per-spectrum RV epochs."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if maxrec_per_batch < batch_size:
        raise ValueError("maxrec_per_batch must be at least batch_size")
    targets = normalize_dr3_source_ids(source_ids)
    target_set = set(targets)
    if not targets:
        return _standardize_rows(pd.DataFrame(), spec, set()), []

    frames: list[pd.DataFrame] = []
    receipts: list[DR3SpectrumQueryReceipt] = []
    seen_obsids: set[int] = set()
    for batch_index, batch in enumerate(_chunks(targets, batch_size)):
        query = build_exact_dr3_spectrum_query(spec, batch)
        raw = service.run_sync(query, maxrec=maxrec_per_batch)
        standardized = _standardize_rows(raw, spec, target_set)
        current_obsids = set(
            pd.to_numeric(standardized.get("obsid", pd.Series(dtype=int))).astype(int)
        )
        overlap = seen_obsids.intersection(current_obsids)
        if overlap:
            raise LamostDR3SpectrumError(
                "one LAMOST obsid was returned in multiple exact-ID batches"
            )
        seen_obsids.update(current_obsids)
        frames.append(standardized)
        receipts.append(
            DR3SpectrumQueryReceipt(
                table_name=spec.table_name,
                batch_index=batch_index,
                input_source_count=len(batch),
                returned_row_count=len(standardized),
                query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            )
        )

    combined = (
        pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else _standardize_rows(pd.DataFrame(), spec, set())
    )
    return combined.sort_values(
        ["source_id", "mjd", "obsid"], kind="stable"
    ).reset_index(drop=True), receipts


def candidate_safe_dr3_spectrum_summary(
    target_count: int,
    rows: pd.DataFrame,
    receipts: Iterable[DR3SpectrumQueryReceipt],
    *,
    spec: DR3SpectrumSpec = DR3SpectrumSpec(),
) -> dict[str, object]:
    """Aggregate exact spectrum coverage without identifiers or velocities."""

    source_counts = (
        rows.groupby("source_id", sort=False).size()
        if not rows.empty and "source_id" in rows.columns
        else pd.Series(dtype=int)
    )
    success = rows.get("success", pd.Series(False, index=rows.index)).astype(bool)
    clean_counts = (
        rows.loc[success].groupby("source_id", sort=False).size()
        if success.any()
        else pd.Series(dtype=int)
    )
    return {
        "target_gaia_dr3_count": int(target_count),
        "matched_gaia_dr3_count": int(len(source_counts)),
        "unmatched_gaia_dr3_count": int(target_count - len(source_counts)),
        "spectrum_rows": int(len(rows)),
        "pre_snr_quality_pass_rows": int(success.sum()),
        "raw_spectrum_threshold_counts": {
            "ge_2": int(source_counts.ge(2).sum()),
            "ge_3": int(source_counts.ge(3).sum()),
            "ge_5": int(source_counts.ge(5).sum()),
            "ge_7": int(source_counts.ge(7).sum()),
            "ge_10": int(source_counts.ge(10).sum()),
        },
        "pre_snr_quality_threshold_counts": {
            "ge_2": int(clean_counts.ge(2).sum()),
            "ge_3": int(clean_counts.ge(3).sum()),
            "ge_5": int(clean_counts.ge(5).sum()),
            "ge_7": int(clean_counts.ge(7).sum()),
            "ge_10": int(clean_counts.ge(10).sum()),
        },
        "table_contract": spec.to_record(),
        "query_count": sum(1 for _ in receipts),
        "claim_boundary": (
            "Exact Gaia DR3 per-spectrum coverage and quoted RV uncertainties only. "
            "No variability, orbit, binary, or compact-object claim is authorized."
        ),
    }
