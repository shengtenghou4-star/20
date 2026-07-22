"""Exact LAMOST TAP access for the low-resolution multiple-epoch catalogue.

The public bulk catalogue is large and unreliable to transfer inside a short-lived
runner. This module discovers a TAP table containing the documented multiple-epoch
fields and requests only exact Gaia DR2 identifiers. Identity matching is permitted
only when TAP_SCHEMA reports an integer or text Gaia-ID column; floating-point
identity columns fail closed because Gaia identifiers exceed exact binary-float range.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
from typing import Any, Iterable

import pandas as pd

from hou_compact.lamost import parse_exact_int_text

_REQUIRED_COLUMNS = (
    "source_id",
    "gaia_source_id",
    "obs_number",
    "obsid_list",
    "midmjm_list",
    "rv_list",
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_INTEGER_TYPE_TOKENS = ("bigint", "integer", "int8", "int64", "long", "short")
_TEXT_TYPE_TOKENS = ("char", "varchar", "string", "unicode")
_FORBIDDEN_IDENTITY_TYPE_TOKENS = ("float", "double", "real", "binary")


class LamostTapMecError(RuntimeError):
    """Raised when targeted multiple-epoch access cannot preserve identity."""


@dataclass(frozen=True)
class MecTableSpec:
    table_name: str
    source_id_column: str
    gaia_source_id_column: str
    obs_number_column: str
    obsid_list_column: str
    midmjm_list_column: str
    rv_list_column: str
    gaia_source_id_datatype: str
    identity_literal_mode: str
    priority: int

    def __post_init__(self) -> None:
        for value in (
            self.table_name,
            self.source_id_column,
            self.gaia_source_id_column,
            self.obs_number_column,
            self.obsid_list_column,
            self.midmjm_list_column,
            self.rv_list_column,
        ):
            if not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"unsafe TAP identifier: {value!r}")
        if self.identity_literal_mode not in {"integer", "text"}:
            raise ValueError("identity_literal_mode must be integer or text")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")

    @property
    def selected_columns(self) -> tuple[str, ...]:
        return (
            self.source_id_column,
            self.gaia_source_id_column,
            self.obs_number_column,
            self.obsid_list_column,
            self.midmjm_list_column,
            self.rv_list_column,
        )

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MecQueryReceipt:
    table_name: str
    batch_index: int
    input_identity_count: int
    returned_row_count: int
    query_sha256: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _result_frame(result: Any) -> pd.DataFrame:
    table = result.to_table() if hasattr(result, "to_table") else result
    frame = table.to_pandas() if hasattr(table, "to_pandas") else pd.DataFrame(table)
    frame.columns = [str(column).lower() for column in frame.columns]
    return frame


def _identity_literal_mode(datatype: object) -> str | None:
    text = str(datatype).strip().lower()
    if any(token in text for token in _FORBIDDEN_IDENTITY_TYPE_TOKENS):
        return None
    if any(token in text for token in _INTEGER_TYPE_TOKENS):
        return "integer"
    if any(token in text for token in _TEXT_TYPE_TOKENS):
        return "text"
    return None


def _table_priority(name: str) -> int:
    lowered = name.lower().replace("-", "_")
    score = 20
    if "mec" in lowered:
        score -= 10
    if "multiple" in lowered and "epoch" in lowered:
        score -= 6
    if "lrs" in lowered or "low" in lowered:
        score -= 3
    return max(score, 0)


def discover_mec_table_specs(service: Any, *, maxrec: int = 20_000) -> list[MecTableSpec]:
    """Discover identity-safe TAP tables exposing the documented MEC contract."""

    if maxrec < 1:
        raise ValueError("maxrec must be positive")
    literals = ", ".join(f"'{column}'" for column in _REQUIRED_COLUMNS)
    query = (
        "SELECT table_name, column_name, datatype FROM TAP_SCHEMA.columns "
        f"WHERE column_name IN ({literals})"
    )
    frame = _result_frame(service.run_sync(query, maxrec=maxrec))
    required_metadata = {"table_name", "column_name", "datatype"}
    missing = sorted(required_metadata - set(frame.columns))
    if missing:
        raise LamostTapMecError(f"TAP_SCHEMA result missing columns: {missing}")

    specs: list[MecTableSpec] = []
    for raw_table, group in frame.groupby("table_name", sort=True):
        table_name = str(raw_table)
        if not _IDENTIFIER.fullmatch(table_name):
            continue
        column_map: dict[str, str] = {}
        datatype_map: dict[str, str] = {}
        for row in group.to_dict(orient="records"):
            actual = str(row["column_name"])
            lowered = actual.lower()
            column_map.setdefault(lowered, actual)
            datatype_map.setdefault(lowered, str(row.get("datatype", "")))
        if not set(_REQUIRED_COLUMNS).issubset(column_map):
            continue
        mode = _identity_literal_mode(datatype_map["gaia_source_id"])
        if mode is None:
            continue
        specs.append(
            MecTableSpec(
                table_name=table_name,
                source_id_column=column_map["source_id"],
                gaia_source_id_column=column_map["gaia_source_id"],
                obs_number_column=column_map["obs_number"],
                obsid_list_column=column_map["obsid_list"],
                midmjm_list_column=column_map["midmjm_list"],
                rv_list_column=column_map["rv_list"],
                gaia_source_id_datatype=datatype_map["gaia_source_id"],
                identity_literal_mode=mode,
                priority=_table_priority(table_name),
            )
        )
    specs.sort(key=lambda item: (item.priority, item.table_name))
    if not specs:
        raise LamostTapMecError(
            "no TAP multiple-epoch table preserves Gaia identifiers as integer/text"
        )
    return specs


def normalize_dr2_source_ids(values: Iterable[object]) -> list[int]:
    normalized = {
        parse_exact_int_text(value, name="gaia_dr2_source_id") for value in values
    }
    return sorted(normalized)


def _chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def build_exact_mec_query(spec: MecTableSpec, dr2_source_ids: list[int]) -> str:
    if not dr2_source_ids:
        raise ValueError("dr2_source_ids must not be empty")
    if dr2_source_ids != sorted(set(dr2_source_ids)):
        raise ValueError("dr2_source_ids must be sorted and unique")
    if any(value < 0 for value in dr2_source_ids):
        raise ValueError("dr2_source_ids must be non-negative")
    if spec.identity_literal_mode == "text":
        literals = ", ".join(f"'{value}'" for value in dr2_source_ids)
    else:
        literals = ", ".join(str(value) for value in dr2_source_ids)
    columns = ", ".join(spec.selected_columns)
    return (
        f"SELECT {columns} FROM {spec.table_name} "
        f"WHERE {spec.gaia_source_id_column} IN ({literals})"
    )


def _standardize_rows(frame: pd.DataFrame, spec: MecTableSpec) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*_REQUIRED_COLUMNS, "tap_table"])
    lowered = {str(column).lower(): str(column) for column in frame.columns}
    rename: dict[str, str] = {}
    for canonical, actual in zip(
        _REQUIRED_COLUMNS,
        spec.selected_columns,
        strict=True,
    ):
        source = lowered.get(actual.lower())
        if source is None:
            raise LamostTapMecError(
                f"{spec.table_name} result is missing selected column {actual}"
            )
        rename[source] = canonical
    output = frame.rename(columns=rename).loc[:, list(_REQUIRED_COLUMNS)].copy()
    output["gaia_source_id"] = [
        parse_exact_int_text(value, name="tap.gaia_source_id")
        for value in output["gaia_source_id"]
    ]
    output["tap_table"] = spec.table_name
    return output


def query_exact_mec_rows(
    service: Any,
    spec: MecTableSpec,
    dr2_source_ids: Iterable[object],
    *,
    batch_size: int = 50,
    maxrec_per_batch: int = 100,
) -> tuple[pd.DataFrame, list[MecQueryReceipt]]:
    """Query only exact Gaia DR2 IDs and retain ambiguity status."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if maxrec_per_batch < batch_size:
        raise ValueError("maxrec_per_batch must be at least batch_size")
    targets = normalize_dr2_source_ids(dr2_source_ids)
    target_set = set(targets)
    frames: list[pd.DataFrame] = []
    receipts: list[MecQueryReceipt] = []
    for batch_index, batch in enumerate(_chunks(targets, batch_size)):
        query = build_exact_mec_query(spec, batch)
        frame = _result_frame(service.run_sync(query, maxrec=maxrec_per_batch))
        standardized = _standardize_rows(frame, spec)
        if len(standardized) > maxrec_per_batch:
            raise LamostTapMecError("MEC TAP response exceeded configured maxrec")
        returned = set(standardized.get("gaia_source_id", pd.Series(dtype=int)))
        if not returned.issubset(target_set):
            raise LamostTapMecError("MEC TAP returned Gaia IDs outside the exact query")
        frames.append(standardized)
        receipts.append(
            MecQueryReceipt(
                table_name=spec.table_name,
                batch_index=batch_index,
                input_identity_count=len(batch),
                returned_row_count=len(standardized),
                query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            )
        )
    if not frames:
        return _standardize_rows(pd.DataFrame(), spec), receipts
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if combined.empty:
        combined["tap_mec_status"] = pd.Series(dtype=str)
        return combined, receipts
    counts = combined.groupby("gaia_source_id")["source_id"].transform("size")
    combined["tap_mec_status"] = counts.map(
        lambda count: "accepted_unique" if int(count) == 1 else "ambiguous_multiple_rows"
    )
    return combined.sort_values(
        ["gaia_source_id", "source_id"], kind="stable"
    ).reset_index(drop=True), receipts


def candidate_safe_mec_summary(
    target_count: int,
    rows: pd.DataFrame,
    specs: Iterable[MecTableSpec],
    receipts: Iterable[MecQueryReceipt],
) -> dict[str, object]:
    status = rows.get("tap_mec_status", pd.Series(dtype=str))
    matched_ids = (
        int(rows["gaia_source_id"].nunique())
        if "gaia_source_id" in rows.columns and not rows.empty
        else 0
    )
    accepted_ids = (
        int(rows.loc[status.eq("accepted_unique"), "gaia_source_id"].nunique())
        if "gaia_source_id" in rows.columns and not rows.empty
        else 0
    )
    return {
        "target_gaia_dr2_count": int(target_count),
        "returned_row_count": int(len(rows)),
        "matched_gaia_dr2_count": matched_ids,
        "accepted_unique_gaia_dr2_count": accepted_ids,
        "unmatched_gaia_dr2_count": int(target_count - matched_ids),
        "status_counts": {
            str(key): int(value) for key, value in status.value_counts().items()
        },
        "table_specs": [spec.to_record() for spec in specs],
        "query_count": sum(1 for _ in receipts),
        "claim_boundary": (
            "Exact release-aware multiple-epoch row retrieval only. Returned rows do not "
            "establish RV variability, orbital coherence, binarity, or a compact companion."
        ),
    }
