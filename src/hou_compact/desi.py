"""DESI DR1 single-exposure RV file planning, download, crossmatch, and QC."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import astropy.units as u
import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.time import Time

DESI_MWS_BASE_URL = "https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0"
DESI_SINGLE_EPOCH_RUN = "240521"
DEFAULT_SURVEY_PROGRAMS = (
    ("main", "dark"),
    ("main", "bright"),
    ("main", "backup"),
)
_NESTED_SOURCE_ID_SHIFT = 59 - 12
_DIRECT_DR3_SOURCE_COLUMNS = (
    "GAIA_DR3_SOURCE_ID",
    "GAIA_SOURCE_ID",
    "SOURCE_ID",
)


def gaia_source_id_to_healpix(source_id: int, *, level: int = 12) -> int:
    """Decode Gaia's nested HEALPix index from the source ID."""
    if not isinstance(source_id, int) or source_id < 0:
        raise ValueError("source_id must be a non-negative integer")
    if not isinstance(level, int) or not 0 <= level <= 12:
        raise ValueError("level must be an integer in [0, 12]")
    level12 = source_id // (1 << 35)
    return level12 // (4 ** (12 - level))


# Compatibility alias used by the bounded downloader command.
source_id_to_healpix = gaia_source_id_to_healpix


def desi_healpix_parent(healpix_level6: int) -> int:
    """Return the two-digit parent directory used by DESI's MWS products."""
    if not isinstance(healpix_level6, int) or healpix_level6 < 0:
        raise ValueError("healpix_level6 must be a non-negative integer")
    return healpix_level6 // 100


@dataclass(frozen=True)
class DesiEpochFile:
    """One candidate DESI per-HEALPix single-epoch RV file."""

    healpix: int
    parent: int
    survey: str
    program: str
    url: str

    def as_record(self) -> dict[str, object]:
        return asdict(self)


def single_epoch_file_url(
    healpix_level6: int,
    *,
    survey: str,
    program: str,
    run: str = DESI_SINGLE_EPOCH_RUN,
    base_url: str = DESI_MWS_BASE_URL,
) -> str:
    """Construct one DESI DR1 MWS single-exposure RV file URL."""
    if not run or "/" in run:
        raise ValueError("run must be a simple path component")
    if not survey or "/" in survey:
        raise ValueError("survey must be a simple path component")
    if not program or "/" in program:
        raise ValueError("program must be a simple path component")
    parent = desi_healpix_parent(healpix_level6)
    filename = f"rvtab_spectra-{survey}-{program}-{healpix_level6}.fits"
    return (
        f"{base_url.rstrip('/')}/rv_output/{run}/healpix/{survey}/{program}/"
        f"{parent}/{healpix_level6}/{filename}"
    )


def desi_single_epoch_url(
    healpix: int,
    *,
    survey: str = "main",
    program: str = "bright",
    base_url: str = DESI_MWS_BASE_URL,
) -> str:
    """Compatibility wrapper for the DR1 MWS per-HEALPix URL."""
    return single_epoch_file_url(
        int(healpix),
        survey=survey,
        program=program,
        base_url=base_url,
    )


def plan_single_epoch_files(
    source_ids: Iterable[int],
    *,
    survey_programs: Iterable[tuple[str, str]] = DEFAULT_SURVEY_PROGRAMS,
    run: str = DESI_SINGLE_EPOCH_RUN,
    base_url: str = DESI_MWS_BASE_URL,
) -> list[DesiEpochFile]:
    """Return deterministic unique DESI files covering the Gaia source IDs."""
    healpix_values = sorted({gaia_source_id_to_healpix(int(value), level=6) for value in source_ids})
    combinations = tuple(survey_programs)
    if not combinations:
        raise ValueError("survey_programs must not be empty")
    files = [
        DesiEpochFile(
            healpix=healpix,
            parent=desi_healpix_parent(healpix),
            survey=survey,
            program=program,
            url=single_epoch_file_url(
                healpix,
                survey=survey,
                program=program,
                run=run,
                base_url=base_url,
            ),
        )
        for healpix in healpix_values
        for survey, program in combinations
    ]
    return files


def write_file_plan(files: Iterable[DesiEpochFile], path: Path) -> Path:
    """Write a deterministic CSV file plan."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [item.as_record() for item in files]
    pd.DataFrame.from_records(
        records,
        columns=["healpix", "parent", "survey", "program", "url"],
    ).to_csv(path, index=False)
    return path


def local_path_for_url(url: str, cache_dir: Path) -> Path:
    """Map a DESI URL to a collision-resistant local cache path."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute HTTP(S) URL")
    relative = Path(parsed.netloc) / parsed.path.lstrip("/")
    return cache_dir.resolve() / relative


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
        fallback_epoch = Time(np.asarray(fibermap["MJD"], dtype=float), format="mjd").jyear
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


def _empty_epoch_frame() -> pd.DataFrame:
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

    Small per-HEALPix ``rvtab_spectra`` files often contain only RVTAB, FIBERMAP,
    and SCORES. Direct DR3 IDs are preferred when present. Otherwise Gaia DR3 positions
    and proper motions are propagated to the FIBERMAP reference epoch and matched with
    explicit separation and ambiguity gates. REF_ID is provenance only because it may be
    a Gaia DR2 identifier.
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
            return _empty_epoch_frame()

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
