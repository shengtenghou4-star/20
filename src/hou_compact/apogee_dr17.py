"""SDSS DR17 APOGEE exact Gaia identity and visit-level RV contract.

SkyServer exposes Gaia EDR3 identity on ``apogeeStar``, an explicit
``apogeeStarAllVisit`` mapping, and visit-level MJD/JD/VHELIO/VRELERR fields on
``apogeeVisit``.  This module builds bounded exact-ID joins and emits the common
HOU-COMPACT epoch schema.  Source-level rows remain encrypted research data.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from hou_compact.lamost import parse_exact_int_text


class ApogeeDR17Error(RuntimeError):
    """Raised when APOGEE DR17 rows violate the frozen contract."""


def normalize_source_ids(values: Iterable[object]) -> list[int]:
    source_ids = [
        parse_exact_int_text(value, name="candidate.source_id")
        for value in values
    ]
    if not source_ids:
        raise ValueError("at least one Gaia source ID is required")
    if any(source_id <= 0 for source_id in source_ids):
        raise ValueError("Gaia source IDs must be positive")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Gaia source IDs must be unique")
    return source_ids


def build_sample_query() -> str:
    """Build a one-row public join contract without private target IDs."""

    return (
        "SELECT TOP 1 s.gaiaedr3_source_id, v.visit_id, v.mjd, v.jd, "
        "v.vhelio, v.vrelerr, v.snr, v.starflag, v.telescope, v.survey "
        "FROM apogeeStar AS s "
        "JOIN apogeeStarAllVisit AS av ON av.apstar_id = s.apstar_id "
        "JOIN apogeeVisit AS v ON v.visit_id = av.visit_id "
        "WHERE s.gaiaedr3_source_id IS NOT NULL "
        "AND v.vhelio IS NOT NULL AND v.vrelerr > 0 "
        "AND v.starflag = 0 AND v.snr > 20"
    )


def build_exact_visit_query(source_ids: Iterable[object]) -> str:
    """Build one bounded exact Gaia ID join returning all mapped visits."""

    normalized = normalize_source_ids(source_ids)
    if len(normalized) > 40:
        raise ValueError("one APOGEE exact-ID batch may contain at most 40 targets")
    identifiers = ",".join(str(source_id) for source_id in normalized)
    return (
        "SELECT DISTINCT s.gaiaedr3_source_id, v.visit_id, v.mjd, v.jd, "
        "v.vhelio, v.vrelerr, v.snr, v.starflag, v.telescope, v.survey "
        "FROM apogeeStar AS s "
        "JOIN apogeeStarAllVisit AS av ON av.apstar_id = s.apstar_id "
        "JOIN apogeeVisit AS v ON v.visit_id = av.visit_id "
        f"WHERE s.gaiaedr3_source_id IN ({identifiers})"
    )


def _column(frame: pd.DataFrame, wanted: str) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    if wanted.lower() not in mapping:
        raise ApogeeDR17Error(f"APOGEE result is missing {wanted}")
    return mapping[wanted.lower()]


def _visit_numeric_id(values: pd.Series) -> pd.Series:
    """Create a stable integer epoch key without exposing visit strings publicly."""

    hashed = pd.util.hash_pandas_object(
        values.astype("string").fillna(""), index=False
    ).astype("uint64")
    # Fit in signed int64 while retaining deterministic equality semantics.
    return (hashed & np.uint64((1 << 63) - 1)).astype("int64")


def standardize_exact_visits(
    frame: pd.DataFrame,
    requested_ids: Iterable[object],
) -> pd.DataFrame:
    """Retain exact requested identities and emit visit-level epoch rows."""

    targets = set(normalize_source_ids(requested_ids))
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

    required = (
        "gaiaedr3_source_id",
        "visit_id",
        "mjd",
        "jd",
        "vhelio",
        "vrelerr",
        "snr",
        "starflag",
        "telescope",
        "survey",
    )
    mapping = {name: _column(frame, name) for name in required}

    parsed: list[int | None] = []
    for value in frame[mapping["gaiaedr3_source_id"]]:
        try:
            parsed.append(
                parse_exact_int_text(value, name="apogee.gaiaedr3_source_id")
            )
        except (TypeError, ValueError):
            parsed.append(None)
    source_id = pd.Series(parsed, index=frame.index, dtype="Int64")
    selected = frame.assign(_source_id=source_id)
    selected = selected.loc[selected["_source_id"].isin(targets)].copy()
    if selected.empty:
        return pd.DataFrame(columns=output_columns)

    visit_text = selected[mapping["visit_id"]].astype("string").str.strip()
    if visit_text.eq("").any() or visit_text.isna().any():
        raise ApogeeDR17Error("APOGEE visit_id must be non-empty")
    if visit_text.duplicated().any():
        raise ApogeeDR17Error("APOGEE result contains duplicate visit_id rows")
    visit_key = _visit_numeric_id(visit_text)

    mjd = pd.to_numeric(selected[mapping["mjd"]], errors="coerce")
    jd = pd.to_numeric(selected[mapping["jd"]], errors="coerce")
    derived_mjd = jd - 2_400_000.5
    mjd = mjd.where(np.isfinite(mjd), derived_mjd)
    rv = pd.to_numeric(selected[mapping["vhelio"]], errors="coerce")
    rv_error = pd.to_numeric(selected[mapping["vrelerr"]], errors="coerce")
    snr = pd.to_numeric(selected[mapping["snr"]], errors="coerce")
    starflag = pd.to_numeric(selected[mapping["starflag"]], errors="coerce")
    finite = np.isfinite(mjd) & np.isfinite(rv) & np.isfinite(rv_error)
    quality = finite & rv_error.gt(0) & snr.gt(20) & starflag.fillna(1).eq(0)

    telescope = selected[mapping["telescope"]].astype("string").str.strip()
    survey = selected[mapping["survey"]].astype("string").str.strip()
    output = pd.DataFrame(
        {
            "source_id": selected["_source_id"].astype("int64"),
            "obsid": visit_key,
            "expid": visit_key,
            "mjd": mjd,
            "vrad": rv,
            "vrad_err": rv_error,
            "success": quality.astype(bool),
            "rvs_warn": np.where(quality, 0, 1).astype("int64"),
            "fiberstatus": starflag.fillna(1).astype("int64"),
            "sn_b": snr,
            "sn_r": snr,
            "sn_z": snr,
            "survey": "apogee_dr17_visit",
            "program": survey,
            "source_match_mode": "exact_gaia_edr3_integer_skyserver_join",
            "class": "STAR",
            "subclass": telescope,
        }
    )
    return output.loc[:, output_columns].sort_values(
        ["source_id", "mjd", "obsid"], kind="stable"
    ).reset_index(drop=True)
