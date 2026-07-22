"""Exact DESI epoch extraction through TARGETID or Gaia DR2 ``REF_ID`` bridges."""

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
    "dr2_neighbour_count",
    "dr2_distance_margin_mas",
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


def _validate_dr2_bridge(selected_bridge: pd.DataFrame) -> pd.DataFrame:
    required = {
        "source_id",
        "dr2_source_id",
        "dr2_bridge_status",
        "dr2_angular_distance_mas",
        "dr2_neighbour_count",
        "dr2_distance_margin_mas",
    }
    missing = sorted(required - set(selected_bridge.columns))
    if missing:
        raise KeyError(f"Gaia DR2 bridge is missing columns: {missing}")
    frame = selected_bridge.copy()
    frame["source_id"] = pd.to_numeric(frame["source_id"], errors="raise").astype("int64")
    frame["dr2_source_id"] = pd.to_numeric(
        frame["dr2_source_id"], errors="raise"
    ).astype("int64")
    frame["dr2_angular_distance_mas"] = pd.to_numeric(
        frame["dr2_angular_distance_mas"], errors="raise"
    ).astype(float)
    frame["dr2_neighbour_count"] = pd.to_numeric(
        frame["dr2_neighbour_count"], errors="raise"
    ).astype("int64")
    frame["dr2_distance_margin_mas"] = pd.to_numeric(
        frame["dr2_distance_margin_mas"], errors="coerce"
    ).astype(float)
    frame = frame.loc[
        frame["dr2_bridge_status"].eq("accepted_unique_or_separated_nearest")
    ].copy()
    if frame["source_id"].duplicated().any():
        raise ValueError("accepted Gaia DR2 bridge has duplicate DR3 source rows")
    conflicting = frame.groupby("dr2_source_id")["source_id"].nunique()
    if (conflicting > 1).any():
        values = conflicting.loc[conflicting > 1].index.astype(str).tolist()[:5]
        raise ValueError(f"Gaia DR2 source maps to multiple DR3 sources: {values}")
    return frame.sort_values("dr2_source_id", kind="stable")


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


def _column_or_default(
    table: object,
    name: str,
    mask: np.ndarray,
    default: object,
) -> np.ndarray:
    if name in table.names:
        return np.asarray(table[name])[mask]
    return np.full(int(np.sum(mask)), default)


def _base_epoch_frame(
    *,
    rvtab: object,
    fibermap: object,
    scores: object,
    mask: np.ndarray,
    source_ids: np.ndarray,
    survey: str,
    program: str,
    healpix: int,
    source_match_mode: str,
    source_match_separation_arcsec: np.ndarray,
    dr2_neighbour_count: np.ndarray,
    dr2_distance_margin_mas: np.ndarray,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": source_ids.astype(np.int64),
            "targetid": _column_or_default(rvtab, "TARGETID", mask, -1),
            "expid": _column_or_default(rvtab, "EXPID", mask, -1),
            "mjd": _column_or_default(rvtab, "MJD", mask, np.nan),
            "vrad": _column_or_default(rvtab, "VRAD", mask, np.nan),
            "vrad_err": _column_or_default(rvtab, "VRAD_ERR", mask, np.nan),
            "success": _column_or_default(rvtab, "SUCCESS", mask, False),
            "rvs_warn": _column_or_default(rvtab, "RVS_WARN", mask, -1),
            "fiberstatus": _column_or_default(fibermap, "FIBERSTATUS", mask, -1),
            "sn_b": _column_or_default(scores, "MEDIAN_COADD_SNR_B", mask, np.nan),
            "sn_r": _column_or_default(scores, "MEDIAN_COADD_SNR_R", mask, np.nan),
            "sn_z": _column_or_default(scores, "MEDIAN_COADD_SNR_Z", mask, np.nan),
            "survey": survey,
            "program": program,
            "healpix": int(healpix),
            "source_match_mode": source_match_mode,
            "source_match_separation_arcsec": source_match_separation_arcsec,
            "desi_ref_id": _column_or_default(fibermap, "REF_ID", mask, -1),
            "desi_ref_cat": _column_or_default(fibermap, "REF_CAT", mask, ""),
            "dr2_neighbour_count": dr2_neighbour_count,
            "dr2_distance_margin_mas": dr2_distance_margin_mas,
        },
        columns=_EXACT_EPOCH_COLUMNS,
    )


def extract_single_epoch_rows_by_targetid(
    path: Path,
    selected_targets: pd.DataFrame,
    *,
    survey: str,
    program: str,
    healpix: int,
) -> pd.DataFrame:
    """Extract rows by exact DESI TARGETID from the Data Lab Gaia/zpix crossmatch."""
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
        frame = _base_epoch_frame(
            rvtab=rvtab,
            fibermap=fibermap,
            scores=scores,
            mask=mask,
            source_ids=_mapped_values(
                matched_targetid, source_by_target, dtype=np.int64
            ),
            survey=survey,
            program=program,
            healpix=healpix,
            source_match_mode="official_datalab_zpix_targetid",
            source_match_separation_arcsec=_mapped_values(
                matched_targetid, separation_by_target, dtype=float
            ),
            dr2_neighbour_count=np.full(int(np.sum(mask)), -1, dtype=np.int64),
            dr2_distance_margin_mas=np.full(int(np.sum(mask)), np.nan),
        )
    return frame.sort_values(
        ["source_id", "targetid", "expid"], kind="stable"
    ).reset_index(drop=True)


def extract_single_epoch_rows_by_dr2_refid(
    path: Path,
    selected_bridge: pd.DataFrame,
    *,
    survey: str,
    program: str,
    healpix: int,
) -> pd.DataFrame:
    """Recover rows through an audited DR3→DR2 bridge and exact DESI ``REF_ID``.

    DESI DR1 documents ``REF_CAT='G2'`` and ``REF_ID`` as Gaia DR2 source identifiers.
    The bridge must already have passed the Gaia neighbourhood ambiguity audit.  No
    positional match is performed in this function.
    """
    bridge = _validate_dr2_bridge(selected_bridge)
    if bridge.empty:
        return _empty_exact_epoch_frame()
    source_by_dr2 = dict(
        zip(bridge["dr2_source_id"], bridge["source_id"], strict=True)
    )
    separation_by_dr2 = dict(
        zip(
            bridge["dr2_source_id"],
            bridge["dr2_angular_distance_mas"] / 1000.0,
            strict=True,
        )
    )
    count_by_dr2 = dict(
        zip(bridge["dr2_source_id"], bridge["dr2_neighbour_count"], strict=True)
    )
    margin_by_dr2 = dict(
        zip(bridge["dr2_source_id"], bridge["dr2_distance_margin_mas"], strict=True)
    )

    with fits.open(path.resolve(), memmap=True) as hdul:
        for name in ("RVTAB", "FIBERMAP", "SCORES"):
            if name not in hdul:
                raise KeyError(f"missing required HDU {name} in {path}")
        rvtab = hdul["RVTAB"].data
        fibermap = hdul["FIBERMAP"].data
        scores = hdul["SCORES"].data
        _validate_alignment(rvtab, fibermap, scores)
        for name in ("REF_ID", "REF_CAT"):
            if name not in fibermap.names:
                raise KeyError(f"FIBERMAP has no {name} column for Gaia DR2 recovery")
        ref_id = np.asarray(fibermap["REF_ID"], dtype=np.int64)
        ref_cat = np.char.upper(
            np.char.strip(np.asarray(fibermap["REF_CAT"]).astype(str))
        )
        selected_ids = np.asarray(sorted(source_by_dr2), dtype=np.int64)
        mask = (ref_cat == "G2") & np.isin(ref_id, selected_ids)
        if not np.any(mask):
            return _empty_exact_epoch_frame()
        matched_dr2 = ref_id[mask]
        frame = _base_epoch_frame(
            rvtab=rvtab,
            fibermap=fibermap,
            scores=scores,
            mask=mask,
            source_ids=_mapped_values(matched_dr2, source_by_dr2, dtype=np.int64),
            survey=survey,
            program=program,
            healpix=healpix,
            source_match_mode="gaia_dr3_dr2_neighbourhood_ref_id",
            source_match_separation_arcsec=_mapped_values(
                matched_dr2, separation_by_dr2, dtype=float
            ),
            dr2_neighbour_count=_mapped_values(
                matched_dr2, count_by_dr2, dtype=np.int64
            ),
            dr2_distance_margin_mas=_mapped_values(
                matched_dr2, margin_by_dr2, dtype=float
            ),
        )
    return frame.sort_values(
        ["source_id", "targetid", "expid"], kind="stable"
    ).reset_index(drop=True)
