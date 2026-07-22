"""Exact DESI TARGETID extraction for official Gaia-to-zpix crossmatches."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits

_EXACT_EPOCH_COLUMNS = [
    "source_id",
    "targetid",
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
    "healpix",
    "source_match_mode",
    "source_match_separation_arcsec",
    "desi_ref_id",
    "desi_ref_cat",
]


def _empty_exact_epoch_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=_EXACT_EPOCH_COLUMNS)


def _validate_target_map(selected_targets: pd.DataFrame) -> pd.DataFrame:
    required = {"source_id", "targetid"}
    missing = sorted(required - set(selected_targets.columns))
    if missing:
        raise KeyError(f"exact overlap is missing columns: {missing}")
    frame = selected_targets.copy()
    frame["source_id"] = pd.to_numeric(frame["source_id"], errors="raise").astype("int64")
    frame["targetid"] = pd.to_numeric(frame["targetid"], errors="raise").astype("int64")
    if "match_distance_arcsec" not in frame.columns:
        frame["match_distance_arcsec"] = np.nan
    else:
        frame["match_distance_arcsec"] = pd.to_numeric(
            frame["match_distance_arcsec"], errors="raise"
        ).astype(float)
    conflicting = frame.groupby("targetid")["source_id"].nunique()
    if (conflicting > 1).any():
        values = conflicting.loc[conflicting > 1].index.astype(str).tolist()[:5]
        raise ValueError(f"DESI TARGETID maps to multiple Gaia sources: {values}")
    return frame.sort_values(
        ["targetid", "match_distance_arcsec"], kind="stable", na_position="last"
    ).drop_duplicates("targetid", keep="first")


def _validate_alignment(rvtab: object, fibermap: object, scores: object) -> None:
    lengths = (len(rvtab), len(fibermap), len(scores))
    if len(set(lengths)) != 1:
        raise ValueError(f"RVTAB/FIBERMAP/SCORES rows are not aligned: {lengths}")
    for column in ("TARGETID", "EXPID"):
        if column in rvtab.names and column in fibermap.names:
            if not np.array_equal(rvtab[column], fibermap[column]):
                raise ValueError(f"RVTAB and FIBERMAP {column} rows are not aligned")


def _mapped_values(
    values: np.ndarray,
    mapping: Mapping[int, int | float],
    *,
    dtype: object,
) -> np.ndarray:
    return np.asarray([mapping[int(value)] for value in values], dtype=dtype)


def extract_single_epoch_rows_by_targetid(
    path: Path,
    selected_targets: pd.DataFrame,
    *,
    survey: str,
    program: str,
    healpix: int,
) -> pd.DataFrame:
    """Extract rows by exact DESI TARGETID from the official Gaia/zpix crossmatch.

    This path deliberately avoids positional rematching.  The Gaia source ID is attached
    only through the caller-provided official crossmatch table, while TARGETID is matched
    exactly against the per-exposure RV product.
    """
    targets = _validate_target_map(selected_targets)
    if targets.empty:
        return _empty_exact_epoch_frame()
    source_by_target = dict(zip(targets["targetid"], targets["source_id"], strict=True))
    separation_by_target = dict(
        zip(targets["targetid"], targets["match_distance_arcsec"], strict=True)
    )

    with fits.open(path.resolve(), memmap=True) as hdul:
        for name in ("RVTAB", "FIBERMAP", "SCORES"):
            if name not in hdul:
                raise KeyError(f"missing required HDU {name} in {path}")
        rvtab = hdul["RVTAB"].data
        fibermap = hdul["FIBERMAP"].data
        scores = hdul["SCORES"].data
        _validate_alignment(rvtab, fibermap, scores)
        if "TARGETID" not in rvtab.names:
            raise KeyError("RVTAB has no TARGETID column for exact extraction")
        rv_targetid = np.asarray(rvtab["TARGETID"], dtype=np.int64)
        selected_ids = np.asarray(sorted(source_by_target), dtype=np.int64)
        mask = np.isin(rv_targetid, selected_ids)
        if not np.any(mask):
            return _empty_exact_epoch_frame()
        matched_targetid = rv_targetid[mask]

        def column_or_default(table: object, name: str, default: object) -> np.ndarray:
            if name in table.names:
                return np.asarray(table[name])[mask]
            return np.full(int(np.sum(mask)), default)

        frame = pd.DataFrame(
            {
                "source_id": _mapped_values(
                    matched_targetid, source_by_target, dtype=np.int64
                ),
                "targetid": matched_targetid,
                "expid": column_or_default(rvtab, "EXPID", -1),
                "mjd": column_or_default(rvtab, "MJD", np.nan),
                "vrad": column_or_default(rvtab, "VRAD", np.nan),
                "vrad_err": column_or_default(rvtab, "VRAD_ERR", np.nan),
                "success": column_or_default(rvtab, "SUCCESS", False),
                "rvs_warn": column_or_default(rvtab, "RVS_WARN", -1),
                "fiberstatus": column_or_default(fibermap, "FIBERSTATUS", -1),
                "sn_b": column_or_default(scores, "MEDIAN_COADD_SNR_B", np.nan),
                "sn_r": column_or_default(scores, "MEDIAN_COADD_SNR_R", np.nan),
                "sn_z": column_or_default(scores, "MEDIAN_COADD_SNR_Z", np.nan),
                "survey": survey,
                "program": program,
                "healpix": int(healpix),
                "source_match_mode": "official_datalab_zpix_targetid",
                "source_match_separation_arcsec": _mapped_values(
                    matched_targetid, separation_by_target, dtype=float
                ),
                "desi_ref_id": column_or_default(fibermap, "REF_ID", -1),
                "desi_ref_cat": column_or_default(fibermap, "REF_CAT", ""),
            },
            columns=_EXACT_EPOCH_COLUMNS,
        )
    return frame.sort_values(
        ["source_id", "targetid", "expid"], kind="stable"
    ).reset_index(drop=True)
