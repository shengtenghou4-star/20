"""Duplicate-safe assembly of final HOU-COMPACT evidence tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from hou_compact.claim_readiness import assess_claim_readiness


@dataclass(frozen=True)
class EvidenceMergeResult:
    """Merged source rows plus per-table coverage counts."""

    frame: pd.DataFrame
    coverage: dict[str, dict[str, int]]


def _validate_unique_keys(
    frame: pd.DataFrame,
    *,
    name: str,
    keys: Sequence[str],
) -> None:
    missing = [key for key in keys if key not in frame.columns]
    if missing:
        raise KeyError(f"{name} is missing keys: {missing}")
    if frame.duplicated(list(keys)).any():
        raise ValueError(f"{name} contains duplicate source/solution rows")


def merge_claim_evidence(
    base: pd.DataFrame,
    evidence_tables: Mapping[str, pd.DataFrame],
    *,
    keys: tuple[str, str] = ("source_id", "solution_id"),
) -> EvidenceMergeResult:
    """Left-merge named evidence tables and evaluate final claim readiness.

    Every merge is one-to-one. Overlapping non-key columns are rejected rather than
    silently suffixed, because ambiguous provenance is unacceptable in the final audit.
    Missing source rows are retained and marked with a table-specific presence flag.
    """

    _validate_unique_keys(base, name="base", keys=keys)
    merged = base.copy()
    coverage: dict[str, dict[str, int]] = {}

    for raw_name, table in evidence_tables.items():
        name = str(raw_name).strip()
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"invalid evidence table name: {raw_name!r}")
        _validate_unique_keys(table, name=name, keys=keys)
        overlap = sorted((set(merged.columns) & set(table.columns)) - set(keys))
        if overlap:
            raise ValueError(f"{name} has ambiguous overlapping columns: {overlap}")

        presence = f"{name}_row_present"
        incoming = table.copy()
        incoming[presence] = True
        merged = merged.merge(
            incoming,
            on=list(keys),
            how="left",
            validate="one_to_one",
            sort=False,
        )
        merged[presence] = merged[presence].fillna(False).astype(bool)
        matched = int(merged[presence].sum())
        coverage[name] = {
            "input_rows": len(table),
            "matched_base_rows": matched,
            "missing_base_rows": len(merged) - matched,
        }

    readiness = pd.DataFrame.from_records(
        assess_claim_readiness(row) for _, row in merged.iterrows()
    )
    if len(readiness) != len(merged):
        raise RuntimeError("claim-readiness output row count changed during merge")
    for column in readiness.columns:
        if column in merged.columns:
            raise ValueError(f"claim-readiness output collides with column: {column}")
        merged[column] = readiness[column].to_numpy()

    return EvidenceMergeResult(frame=merged, coverage=coverage)
