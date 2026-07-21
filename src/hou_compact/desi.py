"""DESI DR1 single-exposure RV file planning, download, crossmatch, and QC."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import astropy.units as u
import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time

DESI_IRON_BASE_URL = (
    "https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0/"
    "rv_output/240521/healpix"
)
_NESTED_SOURCE_ID_SHIFT = 59 - 12
_DIRECT_DR3_SOURCE_COLUMNS = (
    "GAIA_DR3_SOURCE_ID",
    "GAIA_SOURCE_ID",
    "SOURCE_ID",
)


def source_id_to_healpix(source_id: int) -> int:
    """Decode Gaia's nested level-12 HEALPix index from a DR3 source ID."""
    if not isinstance(source_id, (int, np.integer)):
        raise TypeError("source_id must be an integer")
    if source_id < 0:
        raise ValueError("source_id must be non-negative")
    return int(source_id) // (1 << _NESTED_SOURCE_ID_SHIFT)


def desi_single_epoch_url(
    healpix: int,
    *,
    survey: str = "main",
    program: str = "bright",
    base_url: str = DESI_IRON_BASE_URL,
) -> str:
    """Return the DR1 MWS per-HEALPix single-exposure RVSpecFit URL."""
    if not isinstance(healpix, (int, np.integer)) or healpix < 0:
        raise ValueError("healpix must be a non-negative integer")
    if not survey or "/" in survey:
        raise ValueError("survey must be a simple non-empty path component")
    if not program or "/" in program:
        raise ValueError("program must be a simple non-empty path component")
    group = int(healpix) // 100
    filename = f"rvtab_spectra-{survey}-{program}-{int(healpix)}.fits"
    return f"{base_url.rstrip('/')}/{survey}/{program}/{group}/{int(healpix)}/{filename}"


def plan_single_epoch_files(
    source_ids: Iterable[int],
    *,
    surveys: tuple[str, ...] = ("main",),
    programs: tuple[str, ...] = ("bright", "dark", "backup"),
    base_url: str = DESI_IRON_BASE_URL,
) -> pd.DataFrame:
    """Plan unique DESI single-exposure files needed for Gaia source IDs."""
    source_ids = [int(value) for value in source_ids]
    healpix_values = sorted({source_id_to_healpix(value) for value in source_ids})
    rows: list[dict[str, object]] = []
    for healpix in healpix_values:
        for survey in surveys:
            for program in programs:
                rows.append(
                    {
                        "healpix": healpix,
                        "healpix_group": healpix // 100,
                        "survey": survey,
                        "program": program,
                        "url": desi_single_epoch_url(
                            healpix,
                            survey=survey,
                            program=program,
                            base_url=base_url,
                        ),
                    }
                )
    return pd.DataFrame(rows)


def file_size_from_headers(url: str, *, timeout: int = 30) -> int | None:
    """Return Content-Length using HEAD with a byte-range fallback."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    request = Request(url, method="HEAD")
    try:
        with urlopen(request, timeout=timeout) as response:
            header = response.headers.get("Content-Length")
            return int(header) if header is not None else None
    except HTTPError as error:
        if error.code not in {403, 405, 501}:
            raise
    request = Request(url, headers={"Range": "bytes=0-0"})
    with urlopen(request, timeout=timeout) as response:
        content_range = response.headers.get("Content-Range")
        if content_range and "/" in content_range:
            total = content_range.rsplit("/", 1)[1]
            return None if total == "*" else int(total)
        header = response.headers.get("Content-Length")
        return int(header) if header is not None else None


def download_file_bounded(
    url: str,
    destination: Path,
    *,
    maximum_bytes: int,
    timeout: int = 120,
    retries: int = 2,
    chunk_bytes: int = 1024 * 1024,
) -> dict[str, object]:
    """Download one file without ever exceeding the configured byte ceiling."""
    if maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be positive")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        partial.unlink(missing_ok=True)
        received = 0
        try:
            request = Request(url)
            with urlopen(request, timeout=timeout) as response:
                declared_header = response.headers.get("Content-Length")
                declared = int(declared_header) if declared_header else None
                if declared is not None and declared > maximum_bytes:
                    raise ValueError(
                        f"declared file size {declared} exceeds limit {maximum_bytes}"
                    )
                with partial.open("wb") as output:
                    while True:
                        chunk = response.read(chunk_bytes)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > maximum_bytes:
                            raise ValueError(
                                f"download crossed byte limit {maximum_bytes}"
                            )
                        output.write(chunk)
            partial.replace(destination)
            return {
                "url": url,
                "path": str(destination),
                "bytes": received,
                "declared_bytes": declared,
                "attempts": attempt + 1,
            }
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            last_error = error
            partial.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise last_error


def _validate_row_alignment(rvtab: object, fibermap: object, gaia: object | None) -> None:
    lengths = [len(rvtab), len(fibermap)]
    if gaia is not None:
        lengths.append(len(gaia))
    if len(set(lengths)) != 1:
        raise ValueError(f"RVTAB/FIBERMAP/GAIA row counts are not aligned: {lengths}")
    for column in ("TARGETID", "EXPID"):
        if column in rvtab.names and column in fibermap.names:
            if not np.array_equal(rvtab[column], fibermap[column]):
                raise ValueError(f"RVTAB and FIBERMAP {column} rows are not aligned")


def _infer_healpix(path: Path, rvtab: object, supplied: int | None) -> int:
    if supplied is not None:
        if supplied < 0:
            raise ValueError("healpix must be non-negative")
        return int(supplied)
    if "HEALPIX" in rvtab.names and len(rvtab):
        values = np.unique(np.asarray(rvtab["HEALPIX"], dtype=np.int64))
        if len(values) != 1:
            raise ValueError("RVTAB contains multiple HEALPIX values")
        return int(values[0])
    match = re.search(r"-(\d+)\.fits(?:\.gz)?$", path.name)
    if match:
        return int(match.group(1))
    raise ValueError("healpix is absent from RVTAB and could not be inferred from filename")


def _direct_dr3_source_ids(fibermap: object, gaia: object | None) -> np.ndarray | None:
    if gaia is not None and "SOURCE_ID" in gaia.names:
        return np.asarray(gaia["SOURCE_ID"], dtype=np.int64)
    for name in _DIRECT_DR3_SOURCE_COLUMNS:
        if name in fibermap.names:
            return np.asarray(fibermap[name], dtype=np.int64)
    return None


def _source_catalog_frame(sources: object) -> pd.DataFrame | None:
    if isinstance(sources, pd.DataFrame):
        frame = sources.copy()
    elif isinstance(sources, Mapping):
        frame = pd.DataFrame([sources])
    else:
        return None
    required = {"source_id", "gaia_ra", "gaia_dec"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"Gaia source catalogue is missing columns: {missing}")
    if frame["source_id"].duplicated().any():
        raise ValueError("Gaia source catalogue contains duplicate source_id rows")
    return frame.reset_index(drop=True)


def _finite_series(frame: pd.DataFrame, name: str, default: float) -> np.ndarray:
    if name not in frame.columns:
        return np.full(len(frame), default, dtype=float)
    values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
    return np.where(np.isfinite(values), values, default)


def _position_match_dr3_sources(
    fibermap: object,
    sources: pd.DataFrame,
    *,
    maximum_separation_arcsec: float,
    minimum_ambiguity_margin_arcsec: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not math.isfinite(maximum_separation_arcsec) or maximum_separation_arcsec <= 0:
        raise ValueError("maximum_separation_arcsec must be finite and positive")
    if (
        not math.isfinite(minimum_ambiguity_margin_arcsec)
        or minimum_ambiguity_margin_arcsec < 0
    ):
        raise ValueError("minimum_ambiguity_margin_arcsec must be finite and non-negative")
    if len(sources) == 0:
        return (
            np.full(len(fibermap), -1, dtype=np.int64),
            np.full(len(fibermap), np.inf, dtype=float),
            np.zeros(len(fibermap), dtype=bool),
        )
    for name in ("TARGET_RA", "TARGET_DEC"):
        if name not in fibermap.names:
            raise KeyError(
                "per-HEALPix DESI file has no direct Gaia DR3 IDs and FIBERMAP is "
                f"missing {name} for positional crossmatch"
            )

    target_ra = np.asarray(fibermap["TARGET_RA"], dtype=float)
    target_dec = np.asarray(fibermap["TARGET_DEC"], dtype=float)
    target_coords = SkyCoord(target_ra * u.deg, target_dec * u.deg)
    if "REF_EPOCH" in fibermap.names:
        target_epoch = np.asarray(fibermap["REF_EPOCH"], dtype=float)
    else:
        target_epoch = np.full(len(fibermap), np.nan)
    if "MJD" in fibermap.names:
        mjd = np.asarray(fibermap["MJD"], dtype=float)
        fallback_epoch = Time(mjd, format="mjd").jyear
    else:
        fallback_epoch = np.full(len(fibermap), 2016.0)
    target_epoch = np.where(
        np.isfinite(target_epoch) & (target_epoch > 1900.0),
        target_epoch,
        fallback_epoch,
    )

    source_ra = _finite_series(sources, "gaia_ra", float("nan"))
    source_dec = _finite_series(sources, "gaia_dec", float("nan"))
    source_pmra = _finite_series(sources, "pmra", 0.0)
    source_pmdec = _finite_series(sources, "pmdec", 0.0)
    source_epoch = _finite_series(sources, "gaia_ref_epoch", 2016.0)
    if np.any(~np.isfinite(source_ra)) or np.any(~np.isfinite(source_dec)):
        raise ValueError("Gaia source catalogue contains non-finite coordinates")

    separations = np.empty((len(sources), len(fibermap)), dtype=float)
    for index in range(len(sources)):
        source_coord = SkyCoord(
            ra=source_ra[index] * u.deg,
            dec=source_dec[index] * u.deg,
            pm_ra_cosdec=source_pmra[index] * u.mas / u.yr,
            pm_dec=source_pmdec[index] * u.mas / u.yr,
            obstime=Time(source_epoch[index], format="jyear"),
        )
        propagated = source_coord.apply_space_motion(
            new_obstime=Time(target_epoch, format="jyear")
        )
        separations[index] = propagated.separation(target_coords).arcsec

    nearest_index = np.argmin(separations, axis=0)
    nearest = separations[nearest_index, np.arange(len(fibermap))]
    if len(sources) > 1:
        second = np.partition(separations, kth=1, axis=0)[1]
        unambiguous = (second - nearest) >= minimum_ambiguity_margin_arcsec
    else:
        unambiguous = np.ones(len(fibermap), dtype=bool)
    matched = (nearest <= maximum_separation_arcsec) & unambiguous
    source_ids = np.full(len(fibermap), -1, dtype=np.int64)
    source_ids[matched] = sources.iloc[nearest_index[matched]]["source_id"].to_numpy(
        dtype=np.int64
    )
    return source_ids, nearest, matched


def extract_single_epoch_rows(
    path: Path,
    selected_sources: Iterable[int] | pd.DataFrame | Mapping[str, object],
    *,
    survey: str,
    program: str,
    healpix: int | None = None,
    maximum_match_separation_arcsec: float = 1.0,
    minimum_ambiguity_margin_arcsec: float = 0.1,
) -> pd.DataFrame:
    """Extract row-aligned DESI RV epochs for selected Gaia DR3 sources.

    Combined DESI products may contain a row-aligned ``GAIA`` HDU, while the small
    per-HEALPix ``rvtab_spectra`` files used by the bounded downloader commonly contain only
    ``RVTAB``, ``FIBERMAP`` and ``SCORES``. Direct DR3 IDs are used when available. Otherwise
    Gaia DR3 coordinates and proper motions are propagated to the DESI reference epoch and
    matched to ``FIBERMAP.TARGET_RA/TARGET_DEC``. ``REF_ID`` is retained as DESI provenance
    but is never silently interpreted as a DR3 source ID because it may refer to Gaia DR2.
    """
    path = path.resolve()
    source_frame = _source_catalog_frame(selected_sources)
    selected_ids = (
        set(source_frame["source_id"].astype("int64"))
        if source_frame is not None
        else {int(value) for value in selected_sources}
    )
    with fits.open(path, memmap=True) as hdul:
        for name in ("RVTAB", "FIBERMAP", "SCORES"):
            if name not in hdul:
                raise KeyError(f"missing required HDU {name} in {path}")
        rvtab = hdul["RVTAB"].data
        fibermap = hdul["FIBERMAP"].data
        scores = hdul["SCORES"].data
        gaia = hdul["GAIA"].data if "GAIA" in hdul else None
        _validate_row_alignment(rvtab, fibermap, gaia)
        if len(scores) != len(rvtab):
            raise ValueError("SCORES rows are not aligned with RVTAB")

        direct_ids = _direct_dr3_source_ids(fibermap, gaia)
        if direct_ids is not None:
            source_ids = direct_ids
            match_separation = np.full(len(rvtab), np.nan, dtype=float)
            mask = np.isin(source_ids, np.asarray(sorted(selected_ids), dtype=np.int64))
            match_mode = np.full(len(rvtab), "direct_dr3_source_id", dtype=object)
        else:
            if source_frame is None:
                raise KeyError(
                    "per-HEALPix DESI file has no direct Gaia DR3 source-id column; "
                    "pass a Gaia source DataFrame with source_id, gaia_ra and gaia_dec"
                )
            source_ids, match_separation, mask = _position_match_dr3_sources(
                fibermap,
                source_frame,
                maximum_separation_arcsec=maximum_match_separation_arcsec,
                minimum_ambiguity_margin_arcsec=minimum_ambiguity_margin_arcsec,
            )
            match_mode = np.full(len(rvtab), "position_proper_motion", dtype=object)

        file_healpix = _infer_healpix(path, rvtab, healpix)
        if not np.any(mask):
            return pd.DataFrame(
                columns=[
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
            )

        def column_or_default(table: object, name: str, default: object) -> np.ndarray:
            if name in table.names:
                return np.asarray(table[name])[mask]
            return np.full(int(np.sum(mask)), default)

        frame = pd.DataFrame(
            {
                "source_id": source_ids[mask].astype(np.int64),
                "targetid": column_or_default(rvtab, "TARGETID", -1),
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
                "healpix": file_healpix,
                "source_match_mode": match_mode[mask],
                "source_match_separation_arcsec": match_separation[mask],
                "desi_ref_id": column_or_default(fibermap, "REF_ID", -1),
                "desi_ref_cat": column_or_default(fibermap, "REF_CAT", ""),
            }
        )
    return frame


def clean_epoch_mask(
    frame: pd.DataFrame,
    *,
    min_arm_sn: float = 2.0,
    max_vrad_err: float = 20.0,
) -> pd.Series:
    """Return a conservative per-exposure quality mask."""
    required = {
        "success",
        "rvs_warn",
        "fiberstatus",
        "vrad",
        "vrad_err",
        "sn_b",
        "sn_r",
        "sn_z",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"missing required epoch columns: {missing}")
    sn = frame[["sn_b", "sn_r", "sn_z"]].max(axis=1, skipna=True)
    finite = np.isfinite(frame["vrad"]) & np.isfinite(frame["vrad_err"])
    return (
        frame["success"].astype(bool)
        & frame["rvs_warn"].eq(0)
        & frame["fiberstatus"].eq(0)
        & finite
        & frame["vrad_err"].gt(0)
        & frame["vrad_err"].le(max_vrad_err)
        & sn.ge(min_arm_sn)
    )
