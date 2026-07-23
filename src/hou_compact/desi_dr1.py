"""DESI DR1 MWS exact-identity and single-epoch file contracts.

The NOIRLab Astro Data Lab table ``desi_dr1.mws`` provides one coadded MWS row
per DESI target together with Gaia DR3 identity, TARGETID, HEALPix, survey and
program metadata.  Those fields locate public DESI single-epoch RVTAB files.
This module freezes the minimal schema and rejects backup-program measurements
because DESI DR1 documents substantial radial-velocity systematics there.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Iterable

import numpy as np
import pandas as pd

from hou_compact.lamost import parse_exact_int_text

_TABLE_NAME = "desi_dr1.mws"
_REQUIRED_COLUMNS = {
    "source_id",
    "targetid",
    "healpix",
    "survey",
    "program",
    "srcfile",
    "vrad",
    "vrad_err",
    "rvs_warn",
    "success",
    "sn_b",
    "sn_r",
    "sn_z",
}
_ALLOWED_SURVEYS = {"cmx", "main", "special", "sv1", "sv2", "sv3"}
_ALLOWED_PROGRAMS = {"bright", "dark", "other"}


class DesiDR1Error(RuntimeError):
    """Raised when DESI DR1 metadata violates the frozen contract."""


@dataclass(frozen=True)
class DesiMWSContract:
    table_name: str
    available_columns: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _column(frame: pd.DataFrame, wanted: str) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    if wanted.lower() not in mapping:
        raise DesiDR1Error(f"metadata response is missing {wanted}")
    return mapping[wanted.lower()]


def validate_mws_columns(columns: pd.DataFrame) -> DesiMWSContract:
    """Validate the exact identity, locator, RV and quality columns."""

    name_column = _column(columns, "column_name")
    available = {
        str(value).strip().lower() for value in columns[name_column].dropna()
    }
    missing = sorted(_REQUIRED_COLUMNS - available)
    if missing:
        raise DesiDR1Error(f"desi_dr1.mws is missing columns: {missing}")
    return DesiMWSContract(
        table_name=_TABLE_NAME,
        available_columns=tuple(sorted(available)),
    )


def build_sample_query() -> str:
    """Build a one-row non-backup public contract query."""

    return (
        "SELECT TOP 1 source_id, targetid, healpix, survey, program, srcfile, "
        "vrad, vrad_err, rvs_warn, success, sn_b, sn_r, sn_z "
        "FROM desi_dr1.mws WHERE source_id IS NOT NULL "
        "AND targetid IS NOT NULL AND healpix IS NOT NULL "
        "AND program <> 'backup' AND success = 1 "
        "AND vrad IS NOT NULL AND vrad_err > 0"
    )


def build_exact_id_query(source_ids: Iterable[object]) -> str:
    """Build one bounded exact Gaia DR3 query against the coadded MWS table."""

    normalized = [
        parse_exact_int_text(value, name="candidate.source_id")
        for value in source_ids
    ]
    if not normalized:
        raise ValueError("at least one Gaia DR3 source ID is required")
    if len(normalized) != len(set(normalized)):
        raise ValueError("Gaia DR3 source IDs must be unique")
    if len(normalized) > 50:
        raise ValueError("one DESI exact-ID batch may contain at most 50 targets")
    identifiers = ",".join(str(value) for value in normalized)
    return (
        "SELECT source_id, targetid, healpix, survey, program, srcfile, "
        "vrad, vrad_err, rvs_warn, success, sn_b, sn_r, sn_z "
        "FROM desi_dr1.mws "
        f"WHERE source_id IN ({identifiers}) AND program <> 'backup'"
    )


def _normalized_text(value: object) -> str:
    return str(value).strip().lower()


def standardize_coadd_rows(
    frame: pd.DataFrame,
    requested_ids: Iterable[object],
) -> pd.DataFrame:
    """Retain exact non-backup identities and emit locator/coadd columns."""

    targets = {
        parse_exact_int_text(value, name="candidate.source_id")
        for value in requested_ids
    }
    output_columns = [
        "source_id",
        "targetid",
        "healpix",
        "survey",
        "program",
        "srcfile",
        "vrad",
        "vrad_err",
        "rvs_warn",
        "success",
        "sn_b",
        "sn_r",
        "sn_z",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    missing = sorted(_REQUIRED_COLUMNS - set(mapping))
    if missing:
        raise DesiDR1Error(f"DESI MWS result is missing columns: {missing}")

    parsed: list[int | None] = []
    for value in frame[mapping["source_id"]]:
        try:
            parsed.append(parse_exact_int_text(value, name="desi.source_id"))
        except (TypeError, ValueError):
            parsed.append(None)
    source_id = pd.Series(parsed, index=frame.index, dtype="Int64")
    selected = frame.assign(_source_id=source_id)
    selected = selected.loc[selected["_source_id"].isin(targets)].copy()
    if selected.empty:
        return pd.DataFrame(columns=output_columns)

    survey = selected[mapping["survey"]].map(_normalized_text)
    program = selected[mapping["program"]].map(_normalized_text)
    valid_locator = survey.isin(_ALLOWED_SURVEYS) & program.isin(_ALLOWED_PROGRAMS)
    selected = selected.loc[valid_locator].copy()
    survey = survey.loc[valid_locator]
    program = program.loc[valid_locator]
    if selected.empty:
        return pd.DataFrame(columns=output_columns)

    targetid = pd.to_numeric(selected[mapping["targetid"]], errors="raise").astype("int64")
    healpix = pd.to_numeric(selected[mapping["healpix"]], errors="raise").astype("int64")
    if targetid.duplicated().any():
        raise DesiDR1Error("DESI MWS result contains duplicate TARGETID rows")
    if healpix.lt(0).any():
        raise DesiDR1Error("DESI HEALPix values must be non-negative")

    rv = pd.to_numeric(selected[mapping["vrad"]], errors="coerce")
    rv_error = pd.to_numeric(selected[mapping["vrad_err"]], errors="coerce")
    warning = pd.to_numeric(selected[mapping["rvs_warn"]], errors="coerce")
    pipeline_success = pd.to_numeric(selected[mapping["success"]], errors="coerce")
    finite = np.isfinite(rv) & np.isfinite(rv_error)
    quality = finite & rv_error.gt(0) & warning.fillna(1).eq(0) & pipeline_success.eq(1)

    output = pd.DataFrame(
        {
            "source_id": selected["_source_id"].astype("int64"),
            "targetid": targetid,
            "healpix": healpix,
            "survey": survey.astype("string"),
            "program": program.astype("string"),
            "srcfile": selected[mapping["srcfile"]].astype("string"),
            "vrad": rv,
            "vrad_err": rv_error,
            "rvs_warn": warning.fillna(1).astype("int64"),
            "success": quality.astype(bool),
            "sn_b": pd.to_numeric(selected[mapping["sn_b"]], errors="coerce"),
            "sn_r": pd.to_numeric(selected[mapping["sn_r"]], errors="coerce"),
            "sn_z": pd.to_numeric(selected[mapping["sn_z"]], errors="coerce"),
        }
    )
    return output.loc[:, output_columns].sort_values(
        ["source_id", "survey", "program", "healpix", "targetid"], kind="stable"
    ).reset_index(drop=True)


def single_epoch_rvtab_url(
    base_url: str,
    *,
    survey: str,
    program: str,
    healpix: int,
) -> str:
    """Construct the official DR1 single-epoch RVTAB file URL."""

    root = base_url.rstrip("/")
    if not root.startswith("https://"):
        raise ValueError("base_url must use HTTPS")
    normalized_survey = survey.strip().lower()
    normalized_program = program.strip().lower()
    if normalized_survey not in _ALLOWED_SURVEYS:
        raise ValueError("unsupported DESI survey")
    if normalized_program not in _ALLOWED_PROGRAMS:
        raise ValueError("unsupported or excluded DESI program")
    if not isinstance(healpix, int) or healpix < 0:
        raise ValueError("healpix must be a non-negative integer")
    prefix = healpix // 100
    return (
        f"{root}/rv_output/240521/healpix/{normalized_survey}/"
        f"{normalized_program}/{prefix}/{healpix}/"
        f"rvtab_spectra-{normalized_survey}-{normalized_program}-{healpix}.fits"
    )


def safe_path_from_url(url: str) -> str:
    """Return only the public path component for candidate-safe receipts."""

    match = re.fullmatch(r"https://[^/]+(?P<path>/.*)", url)
    if match is None:
        raise ValueError("invalid HTTPS URL")
    return match.group("path")
