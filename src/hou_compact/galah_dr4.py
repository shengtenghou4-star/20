"""GALAH DR4 per-spectrum discovery and exact-identity normalization.

The official GALAH DR4 ``allspec`` catalogue contains one row per spectrum,
Gaia DR3 identity, MJD, primary-component RV and quoted RV uncertainty.  This
module discovers the public Data Central table through TAP metadata and freezes
the minimal schema needed for Dark-668 follow-up.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Iterable

import numpy as np
import pandas as pd

from hou_compact.lamost import parse_exact_int_text

_REQUIRED_COLUMNS = {
    "sobject_id",
    "gaiadr3_source_id",
    "mjd",
    "rv_comp_1",
    "e_rv_comp_1",
    "flag_sp",
    "flag_red",
    "snr_px_ccd3",
}


class GalahDR4Error(RuntimeError):
    """Raised when the public GALAH DR4 contract is ambiguous or invalid."""


@dataclass(frozen=True)
class GalahTableContract:
    table_name: str
    available_columns: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _column(frame: pd.DataFrame, wanted: str) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    if wanted.lower() not in mapping:
        raise GalahDR4Error(f"metadata response is missing {wanted}")
    return mapping[wanted.lower()]


def discover_allspec_table(tables: pd.DataFrame) -> str:
    """Select the unique public GALAH DR4 per-spectrum table from TAP metadata."""

    table_column = _column(tables, "table_name")
    names = [str(value).strip() for value in tables[table_column].dropna()]
    candidates = [
        name
        for name in names
        if "galah" in name.lower()
        and "dr4" in name.lower()
        and ("allspec" in name.lower() or "main_spec" in name.lower())
    ]
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise GalahDR4Error(
            "expected one GALAH DR4 per-spectrum table; "
            f"found {len(unique)}"
        )
    if re.fullmatch(r"[A-Za-z0-9_.]+", unique[0]) is None:
        raise GalahDR4Error("discovered table name contains unsafe characters")
    return unique[0]


def validate_allspec_columns(columns: pd.DataFrame, table_name: str) -> GalahTableContract:
    """Validate the frozen GALAH DR4 identity, epoch, RV and quality columns."""

    name_column = _column(columns, "column_name")
    available = {
        str(value).strip().lower() for value in columns[name_column].dropna()
    }
    missing = sorted(_REQUIRED_COLUMNS - available)
    if missing:
        raise GalahDR4Error(f"GALAH DR4 allspec is missing columns: {missing}")
    return GalahTableContract(
        table_name=table_name,
        available_columns=tuple(sorted(available)),
    )


def build_sample_query(table_name: str) -> str:
    """Build a one-row public schema/value contract query without target IDs."""

    if re.fullmatch(r"[A-Za-z0-9_.]+", table_name) is None:
        raise ValueError("unsafe GALAH table name")
    return (
        "SELECT TOP 1 sobject_id, gaiadr3_source_id, mjd, rv_comp_1, "
        "e_rv_comp_1, flag_sp, flag_red, snr_px_ccd3 "
        f"FROM {table_name} "
        "WHERE gaiadr3_source_id IS NOT NULL "
        "AND rv_comp_1 IS NOT NULL AND e_rv_comp_1 > 0"
    )


def build_exact_id_query(table_name: str, source_ids: Iterable[object]) -> str:
    """Build a bounded exact Gaia DR3 ID query for one small private batch."""

    if re.fullmatch(r"[A-Za-z0-9_.]+", table_name) is None:
        raise ValueError("unsafe GALAH table name")
    normalized = [
        parse_exact_int_text(value, name="candidate.source_id")
        for value in source_ids
    ]
    if not normalized:
        raise ValueError("at least one Gaia DR3 source ID is required")
    if len(normalized) != len(set(normalized)):
        raise ValueError("Gaia DR3 source IDs must be unique")
    if len(normalized) > 50:
        raise ValueError("one GALAH exact-ID batch may contain at most 50 targets")
    identifiers = ",".join(str(value) for value in normalized)
    return (
        "SELECT sobject_id, gaiadr3_source_id, mjd, rv_comp_1, "
        "e_rv_comp_1, flag_sp, flag_red, snr_px_ccd1, snr_px_ccd2, "
        "snr_px_ccd3, snr_px_ccd4, rv_comp_nr, rv_comp_1_p, setup, survey_name "
        f"FROM {table_name} WHERE gaiadr3_source_id IN ({identifiers})"
    )


def standardize_exact_rows(
    frame: pd.DataFrame,
    requested_ids: Iterable[object],
) -> pd.DataFrame:
    """Retain exact requested identities and emit the HOU-COMPACT epoch schema."""

    targets = {
        parse_exact_int_text(value, name="candidate.source_id")
        for value in requested_ids
    }
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
    required = _REQUIRED_COLUMNS
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    missing = sorted(required - set(mapping))
    if missing:
        raise GalahDR4Error(f"GALAH result is missing columns: {missing}")

    parsed: list[int | None] = []
    for value in frame[mapping["gaiadr3_source_id"]]:
        try:
            parsed.append(parse_exact_int_text(value, name="galah.gaiadr3_source_id"))
        except (TypeError, ValueError):
            parsed.append(None)
    source_id = pd.Series(parsed, index=frame.index, dtype="Int64")
    selected = frame.assign(_source_id=source_id)
    selected = selected.loc[selected["_source_id"].isin(targets)].copy()
    if selected.empty:
        return pd.DataFrame(columns=output_columns)

    sobject = pd.to_numeric(selected[mapping["sobject_id"]], errors="raise").astype("int64")
    if sobject.duplicated().any():
        raise GalahDR4Error("GALAH result contains duplicate sobject_id rows")
    mjd = pd.to_numeric(selected[mapping["mjd"]], errors="coerce")
    rv = pd.to_numeric(selected[mapping["rv_comp_1"]], errors="coerce")
    rv_error = pd.to_numeric(selected[mapping["e_rv_comp_1"]], errors="coerce")
    flag_sp = pd.to_numeric(selected[mapping["flag_sp"]], errors="coerce")
    flag_red = pd.to_numeric(selected[mapping["flag_red"]], errors="coerce")
    snr = pd.to_numeric(selected[mapping["snr_px_ccd3"]], errors="coerce")
    finite = np.isfinite(mjd) & np.isfinite(rv) & np.isfinite(rv_error)
    success = (
        finite
        & rv_error.gt(0)
        & flag_sp.fillna(1).eq(0)
        & flag_red.fillna(1).eq(0)
        & snr.gt(30)
    )

    output = pd.DataFrame(
        {
            "source_id": selected["_source_id"].astype("int64"),
            "obsid": sobject,
            "expid": sobject,
            "mjd": mjd,
            "vrad": rv,
            "vrad_err": rv_error,
            "success": success.astype(bool),
            "rvs_warn": np.where(success, 0, 1).astype("int64"),
            "fiberstatus": flag_red.fillna(1).astype("int64"),
            "sn_b": pd.to_numeric(
                selected.get(mapping.get("snr_px_ccd1", "")), errors="coerce"
            ),
            "sn_r": snr,
            "sn_z": pd.to_numeric(
                selected.get(mapping.get("snr_px_ccd4", "")), errors="coerce"
            ),
            "survey": "galah_dr4_allspec",
            "program": selected.get(
                mapping.get("survey_name", ""), pd.Series("GALAH", index=selected.index)
            ).astype("string"),
            "source_match_mode": "exact_gaia_dr3_integer_tap_constraint",
            "class": "STAR",
            "subclass": selected.get(
                mapping.get("setup", ""), pd.Series(pd.NA, index=selected.index)
            ).astype("string"),
        }
    )
    return output.loc[:, output_columns].sort_values(
        ["source_id", "mjd", "obsid"], kind="stable"
    ).reset_index(drop=True)
