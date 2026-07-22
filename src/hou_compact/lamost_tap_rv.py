"""Exact, bounded LAMOST TAP acquisition for per-spectrum RV uncertainties.

The multiple-epoch catalogue identifies relevant spectrum IDs but does not carry
per-spectrum RV uncertainties.  This module discovers TAP tables exposing the
required ``obsid``, ``rv``, and ``rv_err`` columns, then requests only exact obsid
batches.  It never performs positional matching or unrestricted catalogue scans.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd

_REQUIRED_COLUMNS = {"obsid", "rv", "rv_err"}
_DISCOVERY_COLUMNS = (
    "obsid",
    "rv",
    "rv_err",
    "snrg",
    "snri",
    "class",
    "subclass",
    "fibermask",
    "gaia_source_id",
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class LamostTapRvError(RuntimeError):
    """Raised when exact TAP acquisition cannot satisfy the frozen contract."""


@dataclass(frozen=True)
class RvTableSpec:
    table_name: str
    columns: tuple[str, ...]
    priority: int

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.table_name):
            raise ValueError(f"unsafe TAP table identifier: {self.table_name!r}")
        for column in self.columns:
            if not _IDENTIFIER.fullmatch(column):
                raise ValueError(f"unsafe TAP column identifier: {column!r}")
        lowered = {column.lower() for column in self.columns}
        if not _REQUIRED_COLUMNS.issubset(lowered):
            raise ValueError("RV table must expose obsid, rv, and rv_err")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TapQueryReceipt:
    table_name: str
    batch_index: int
    input_obsid_count: int
    returned_row_count: int
    query_sha256: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _result_frame(result: Any) -> pd.DataFrame:
    table = result.to_table() if hasattr(result, "to_table") else result
    frame = table.to_pandas() if hasattr(table, "to_pandas") else pd.DataFrame(table)
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame


def _table_priority(name: str) -> int:
    lowered = name.lower().replace("-", "_")
    if "afgk" in lowered or all(token in lowered for token in ("a", "f", "g", "k")):
        return 0
    if "mstar" in lowered or "m_star" in lowered or "mtype" in lowered:
        return 1
    if "astar" in lowered or "a_star" in lowered or "atype" in lowered:
        return 2
    return 10


def discover_rv_table_specs(service: Any, *, maxrec: int = 20_000) -> list[RvTableSpec]:
    """Discover TAP tables that contain exact per-spectrum RV requirements."""

    if maxrec < 1:
        raise ValueError("maxrec must be positive")
    literals = ", ".join(f"'{column}'" for column in _DISCOVERY_COLUMNS)
    query = (
        "SELECT table_name, column_name FROM TAP_SCHEMA.columns "
        f"WHERE column_name IN ({literals})"
    )
    frame = _result_frame(service.run_sync(query, maxrec=maxrec))
    required = {"table_name", "column_name"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise LamostTapRvError(f"TAP_SCHEMA result missing columns: {missing}")

    specs: list[RvTableSpec] = []
    for raw_table, group in frame.groupby("table_name", sort=True):
        table_name = str(raw_table)
        if not _IDENTIFIER.fullmatch(table_name):
            continue
        original_columns = sorted({str(value) for value in group["column_name"]})
        lowered = {column.lower() for column in original_columns}
        if not _REQUIRED_COLUMNS.issubset(lowered):
            continue
        selected: list[str] = []
        for wanted in _DISCOVERY_COLUMNS:
            matches = [column for column in original_columns if column.lower() == wanted]
            if matches:
                selected.append(matches[0])
        specs.append(
            RvTableSpec(
                table_name=table_name,
                columns=tuple(selected),
                priority=_table_priority(table_name),
            )
        )
    specs.sort(key=lambda item: (item.priority, item.table_name))
    if not specs:
        raise LamostTapRvError("no TAP table exposes obsid, rv, and rv_err")
    return specs


def normalize_obsids(values: Iterable[object]) -> list[int]:
    """Return sorted unique non-negative integer spectrum IDs, failing closed."""

    normalized: set[int] = set()
    for value in values:
        text = str(value).strip()
        if not re.fullmatch(r"[0-9]+", text):
            raise ValueError(f"obsid is not exact non-negative integer text: {value!r}")
        normalized.add(int(text))
    return sorted(normalized)


def _chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def build_exact_obsid_query(spec: RvTableSpec, obsids: list[int]) -> str:
    if not obsids:
        raise ValueError("obsid batch must not be empty")
    if obsids != sorted(set(obsids)) or any(value < 0 for value in obsids):
        raise ValueError("obsids must be sorted unique non-negative integers")
    columns = ", ".join(spec.columns)
    literals = ", ".join(str(value) for value in obsids)
    return f"SELECT {columns} FROM {spec.table_name} WHERE obsid IN ({literals})"


def _standardize_table_rows(frame: pd.DataFrame, spec: RvTableSpec) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "obsid",
                "rv",
                "rv_err",
                "snrg",
                "snri",
                "class",
                "subclass",
                "fibermask",
                "gaia_source_id",
                "tap_table",
                "tap_table_priority",
            ]
        )
    missing = sorted(_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise LamostTapRvError(
            f"{spec.table_name} result missing required columns: {missing}"
        )
    output = frame.copy()
    output["obsid"] = pd.to_numeric(output["obsid"], errors="raise").astype("int64")
    output["rv"] = pd.to_numeric(output["rv"], errors="coerce")
    output["rv_err"] = pd.to_numeric(output["rv_err"], errors="coerce")
    for optional in ("snrg", "snri", "fibermask"):
        if optional in output:
            output[optional] = pd.to_numeric(output[optional], errors="coerce")
        else:
            output[optional] = np.nan
    for optional in ("class", "subclass", "gaia_source_id"):
        if optional not in output:
            output[optional] = ""
    output["tap_table"] = spec.table_name
    output["tap_table_priority"] = spec.priority
    return output.loc[
        :,
        [
            "obsid",
            "rv",
            "rv_err",
            "snrg",
            "snri",
            "class",
            "subclass",
            "fibermask",
            "gaia_source_id",
            "tap_table",
            "tap_table_priority",
        ],
    ]


def query_exact_obsids(
    service: Any,
    specs: Iterable[RvTableSpec],
    obsids: Iterable[object],
    *,
    batch_size: int = 200,
    maxrec_per_batch: int = 500,
) -> tuple[pd.DataFrame, list[TapQueryReceipt]]:
    """Query exact obsids across scoring-ready tables and choose one row per obsid.

    Tables are searched in deterministic scientific priority.  When an obsid occurs
    in more than one subset catalogue, the first finite-positive-error row from the
    highest-priority table is retained.  All duplicate provenance remains summarized
    by ``matched_table_count``; no rows are merged numerically across pipelines.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if maxrec_per_batch < batch_size:
        raise ValueError("maxrec_per_batch must be at least batch_size")
    target_obsids = normalize_obsids(obsids)
    ordered_specs = sorted(specs, key=lambda item: (item.priority, item.table_name))
    if not ordered_specs:
        raise ValueError("at least one RV table spec is required")
    frames: list[pd.DataFrame] = []
    receipts: list[TapQueryReceipt] = []
    for spec in ordered_specs:
        for batch_index, batch in enumerate(_chunks(target_obsids, batch_size)):
            query = build_exact_obsid_query(spec, batch)
            frame = _result_frame(service.run_sync(query, maxrec=maxrec_per_batch))
            standardized = _standardize_table_rows(frame, spec)
            if len(standardized) > maxrec_per_batch:
                raise LamostTapRvError("TAP response exceeded configured maxrec")
            if not standardized.empty and not set(standardized["obsid"]).issubset(batch):
                raise LamostTapRvError("TAP returned obsids outside the exact query batch")
            frames.append(standardized)
            receipts.append(
                TapQueryReceipt(
                    table_name=spec.table_name,
                    batch_index=batch_index,
                    input_obsid_count=len(batch),
                    returned_row_count=len(standardized),
                    query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
                )
            )
    if not frames:
        return _standardize_table_rows(pd.DataFrame(), ordered_specs[0]), receipts
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if combined.empty:
        return combined, receipts
    combined["finite_positive_error"] = (
        np.isfinite(combined["rv"])
        & np.isfinite(combined["rv_err"])
        & combined["rv_err"].gt(0)
    )
    combined["matched_table_count"] = combined.groupby("obsid")["tap_table"].transform(
        "nunique"
    )
    combined = combined.sort_values(
        ["obsid", "finite_positive_error", "tap_table_priority", "tap_table"],
        ascending=[True, False, True, True],
        kind="stable",
    )
    chosen = combined.drop_duplicates("obsid", keep="first").copy()
    chosen["tap_rv_status"] = np.where(
        chosen["finite_positive_error"], "scorable", "invalid_or_missing_uncertainty"
    )
    chosen = chosen.drop(columns=["finite_positive_error"])
    return chosen.sort_values("obsid", kind="stable").reset_index(drop=True), receipts


def candidate_safe_tap_summary(
    target_obsid_count: int,
    rows: pd.DataFrame,
    specs: Iterable[RvTableSpec],
    receipts: Iterable[TapQueryReceipt],
) -> dict[str, object]:
    statuses = rows.get("tap_rv_status", pd.Series(dtype=str))
    duplicates = pd.to_numeric(
        rows.get("matched_table_count", pd.Series(dtype=float)), errors="coerce"
    )
    return {
        "target_obsid_count": int(target_obsid_count),
        "matched_obsid_count": int(len(rows)),
        "scorable_obsid_count": int(statuses.eq("scorable").sum()),
        "invalid_or_missing_uncertainty_count": int(
            statuses.eq("invalid_or_missing_uncertainty").sum()
        ),
        "obsids_seen_in_multiple_tables": int(duplicates.gt(1).sum()),
        "table_specs": [spec.to_record() for spec in specs],
        "query_count": sum(1 for _ in receipts),
        "claim_boundary": (
            "Exact per-spectrum catalogue retrieval only. Matching RV rows does not "
            "establish variability, orbital coherence, binarity, or a compact companion."
        ),
    }
