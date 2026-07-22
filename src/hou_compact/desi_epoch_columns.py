"""Restore official DESI single-exposure timing and S/N columns after source matching.

The per-HEALPix RVSpecFit products keep MJD/NIGHT in FIBERMAP and the arm-level
SN_B/SN_R/SN_Z values in RVTAB. Earlier HOU-COMPACT extraction code used coadd-style
SCORES names, which are not the authoritative columns for these individual exposures.
This module repairs the extracted subset by joining the official row-aligned columns on
(TARGETID, EXPID) and fails closed on ambiguity or missing matches.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits

_KEY_COLUMNS = ("targetid", "expid")
_RESTORED_COLUMNS = ("mjd", "night", "sn_b", "sn_r", "sn_z")


def _required_column(table: object, name: str, hdu_name: str) -> np.ndarray:
    if name not in table.names:
        raise KeyError(f"{hdu_name} is missing required column {name}")
    return np.asarray(table[name])


def restore_single_exposure_columns(
    fits_path: Path,
    extracted_rows: pd.DataFrame,
) -> pd.DataFrame:
    """Replace timing/S/N placeholders with the official DESI exposure columns.

    Parameters
    ----------
    fits_path
        DESI ``rvtab_spectra`` FITS file.
    extracted_rows
        Source-matched subset returned by :func:`hou_compact.desi.extract_single_epoch_rows`.

    Returns
    -------
    pandas.DataFrame
        The same source-matched rows, in the same order, with ``mjd`` and ``night`` from
        FIBERMAP and ``sn_b``, ``sn_r``, ``sn_z`` from RVTAB.
    """
    frame = extracted_rows.copy()
    missing_keys = sorted(set(_KEY_COLUMNS) - set(frame.columns))
    if missing_keys:
        raise KeyError(f"extracted_rows is missing key columns: {missing_keys}")
    if frame.empty:
        for name in _RESTORED_COLUMNS:
            if name not in frame.columns:
                frame[name] = pd.Series(dtype=float if name != "night" else "Int64")
        frame["official_epoch_columns_restored"] = pd.Series(dtype=bool)
        return frame

    with fits.open(Path(fits_path).resolve(), memmap=True) as hdul:
        for name in ("RVTAB", "FIBERMAP"):
            if name not in hdul:
                raise KeyError(f"missing required HDU {name} in {fits_path}")
        rvtab = hdul["RVTAB"].data
        fibermap = hdul["FIBERMAP"].data
        if len(rvtab) != len(fibermap):
            raise ValueError("RVTAB and FIBERMAP rows are not aligned")

        # FITS binary tables are commonly big-endian. Explicit astype calls create
        # native-endian NumPy arrays before pandas merge/groupby operations.
        rv_targetid = _required_column(rvtab, "TARGETID", "RVTAB").astype(np.int64)
        rv_expid = _required_column(rvtab, "EXPID", "RVTAB").astype(np.int64)
        fm_targetid = _required_column(fibermap, "TARGETID", "FIBERMAP").astype(np.int64)
        fm_expid = _required_column(fibermap, "EXPID", "FIBERMAP").astype(np.int64)
        if not np.array_equal(rv_targetid, fm_targetid):
            raise ValueError("RVTAB and FIBERMAP TARGETID rows are not aligned")
        if not np.array_equal(rv_expid, fm_expid):
            raise ValueError("RVTAB and FIBERMAP EXPID rows are not aligned")

        official = pd.DataFrame(
            {
                "targetid": rv_targetid,
                "expid": rv_expid,
                "mjd": _required_column(fibermap, "MJD", "FIBERMAP").astype(np.float64),
                "night": _required_column(fibermap, "NIGHT", "FIBERMAP").astype(np.int64),
                "sn_b": _required_column(rvtab, "SN_B", "RVTAB").astype(np.float64),
                "sn_r": _required_column(rvtab, "SN_R", "RVTAB").astype(np.float64),
                "sn_z": _required_column(rvtab, "SN_Z", "RVTAB").astype(np.float64),
            }
        )

    if official.duplicated(list(_KEY_COLUMNS)).any():
        raise ValueError("DESI file contains duplicate TARGETID/EXPID rows")

    frame["_original_row_order"] = np.arange(len(frame), dtype=np.int64)
    frame = frame.drop(columns=list(_RESTORED_COLUMNS), errors="ignore")
    merged = frame.merge(
        official,
        how="left",
        on=list(_KEY_COLUMNS),
        validate="many_to_one",
        indicator="_official_epoch_match",
    )
    unmatched = merged["_official_epoch_match"].ne("both")
    if unmatched.any():
        raise ValueError(
            f"{int(unmatched.sum())} extracted rows could not be matched back to RVTAB/FIBERMAP"
        )
    merged = merged.drop(columns="_official_epoch_match")
    if not np.all(np.isfinite(merged[["mjd", "sn_b", "sn_r", "sn_z"]].to_numpy(float))):
        raise ValueError("official DESI timing/S/N columns contain non-finite values")
    merged["official_epoch_columns_restored"] = True
    return (
        merged.sort_values("_original_row_order", kind="stable")
        .drop(columns="_original_row_order")
        .reset_index(drop=True)
    )
