"""DESI DR1 MWS single-epoch file planning and extraction helpers.

The module turns Gaia DR3 source identifiers into the nested HEALPix level used by
DESI MWS files, constructs immutable public-data URLs, and extracts row-aligned
RVTAB/FIBERMAP/GAIA measurements without assigning astrophysical labels.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits

DESI_MWS_BASE_URL = "https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0"
DESI_SINGLE_EPOCH_RUN = "240521"
DEFAULT_SURVEY_PROGRAMS: tuple[tuple[str, str], ...] = (
    ("main", "bright"),
    ("main", "dark"),
    ("main", "backup"),
)


def gaia_source_id_to_healpix(source_id: int, level: int = 6) -> int:
    """Decode the nested Gaia HEALPix index at ``level`` from a DR3 source ID.

    Gaia encodes the level-12 nested HEALPix number in the high-order bits. For
    level ``n`` the divisor is ``2**(59 - 2*n)``. DESI MWS per-pixel products use
    level 6 (NSIDE=64), so level 6 is the default.
    """
    if isinstance(source_id, bool) or not isinstance(source_id, (int, np.integer)):
        raise TypeError("source_id must be an integer")
    if source_id < 0:
        raise ValueError("source_id must be non-negative")
    if not isinstance(level, int) or not 0 <= level <= 12:
        raise ValueError("level must be an integer in [0, 12]")
    return int(source_id) // (1 << (59 - 2 * level))


def desi_healpix_parent(healpix: int) -> int:
    """Return the two-digit grouping directory used by DESI MWS products."""
    if isinstance(healpix, bool) or not isinstance(healpix, (int, np.integer)):
        raise TypeError("healpix must be an integer")
    if healpix < 0:
        raise ValueError("healpix must be non-negative")
    return int(healpix) // 100


@dataclass(frozen=True, order=True)
class DesiEpochFile:
    """One DESI DR1 MWS single-epoch RVTAB file target."""

    survey: str
    program: str
    healpix: int
    base_url: str = DESI_MWS_BASE_URL
    run: str = DESI_SINGLE_EPOCH_RUN

    def __post_init__(self) -> None:
        for name, value in (("survey", self.survey), ("program", self.program), ("run", self.run)):
            if not value or "/" in value or ".." in value:
                raise ValueError(f"unsafe or empty {name}: {value!r}")
        if self.healpix < 0:
            raise ValueError("healpix must be non-negative")

    @property
    def relative_path(self) -> str:
        parent = desi_healpix_parent(self.healpix)
        filename = f"rvtab_spectra-{self.survey}-{self.program}-{self.healpix}.fits"
        return (
            f"rv_output/{self.run}/healpix/{self.survey}/{self.program}/"
            f"{parent}/{self.healpix}/{filename}"
        )

    @property
    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.relative_path}"

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record.update(
            {
                "parent": desi_healpix_parent(self.healpix),
                "relative_path": self.relative_path,
                "url": self.url,
            }
        )
        return record


def plan_single_epoch_files(
    source_ids: Iterable[int],
    survey_programs: Sequence[tuple[str, str]] = DEFAULT_SURVEY_PROGRAMS,
) -> list[DesiEpochFile]:
    """Construct a deterministic, de-duplicated DESI file plan for Gaia IDs."""
    healpixels = sorted(
        {gaia_source_id_to_healpix(int(source_id), level=6) for source_id in source_ids}
    )
    pairs = sorted(set(survey_programs))
    return [
        DesiEpochFile(survey, program, healpix)
        for healpix in healpixels
        for survey, program in pairs
    ]


def write_file_plan(plan: Sequence[DesiEpochFile], output_path: Path) -> pd.DataFrame:
    """Write a stable CSV file plan and return the corresponding dataframe."""
    frame = pd.DataFrame([item.to_record() for item in plan])
    if not frame.empty:
        frame = frame.sort_values(
            ["healpix", "survey", "program"], kind="stable"
        ).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return frame


def extract_single_epoch_rows(
    fits_path: Path,
    source_ids: Iterable[int],
) -> pd.DataFrame:
    """Extract row-aligned DESI single-epoch measurements for selected Gaia IDs.

    This function deliberately returns raw measurements and flags. Scientific quality
    cuts, backup-program RV corrections, and orbit likelihoods are later stages.
    """
    selected = np.asarray(sorted({int(value) for value in source_ids}), dtype=np.int64)
    columns = [
        "source_id",
        "targetid",
        "expid",
        "mjd",
        "night",
        "vrad",
        "vrad_err",
        "rvs_warn",
        "success",
        "sn_b",
        "sn_r",
        "sn_z",
        "fiberstatus",
        "healpix",
    ]
    if selected.size == 0:
        return pd.DataFrame(columns=columns)

    with fits.open(fits_path, memmap=True) as hdul:
        rvtab = hdul["RVTAB"].data
        fibermap = hdul["FIBERMAP"].data
        gaia = hdul["GAIA"].data

        if not (len(rvtab) == len(fibermap) == len(gaia)):
            raise ValueError("RVTAB, FIBERMAP, and GAIA HDUs are not row-aligned")

        mask = np.isin(np.asarray(gaia["SOURCE_ID"], dtype=np.int64), selected)
        if not np.any(mask):
            return pd.DataFrame(columns=columns)

        rv_targetid = np.asarray(rvtab["TARGETID"])[mask]
        fiber_targetid = np.asarray(fibermap["TARGETID"])[mask]
        if not np.array_equal(rv_targetid, fiber_targetid):
            raise ValueError("TARGETID mismatch between RVTAB and FIBERMAP")

        data = {
            "source_id": np.asarray(gaia["SOURCE_ID"], dtype=np.int64)[mask],
            "targetid": rv_targetid,
            "expid": np.asarray(rvtab["EXPID"])[mask],
            "mjd": np.asarray(fibermap["MJD"])[mask],
            "night": np.asarray(fibermap["NIGHT"])[mask],
            "vrad": np.asarray(rvtab["VRAD"], dtype=float)[mask],
            "vrad_err": np.asarray(rvtab["VRAD_ERR"], dtype=float)[mask],
            "rvs_warn": np.asarray(rvtab["RVS_WARN"])[mask],
            "success": np.asarray(rvtab["SUCCESS"], dtype=bool)[mask],
            "sn_b": np.asarray(rvtab["SN_B"], dtype=float)[mask],
            "sn_r": np.asarray(rvtab["SN_R"], dtype=float)[mask],
            "sn_z": np.asarray(rvtab["SN_Z"], dtype=float)[mask],
            "fiberstatus": np.asarray(fibermap["FIBERSTATUS"])[mask],
            "healpix": np.asarray(rvtab["HEALPIX"])[mask],
        }
        return pd.DataFrame(data, columns=columns).sort_values(
            ["source_id", "mjd", "expid"], kind="stable"
        ).reset_index(drop=True)


def clean_epoch_mask(
    rows: pd.DataFrame,
    *,
    min_arm_sn: float = 2.0,
    max_vrad_err: float = 20.0,
) -> pd.Series:
    """Return a conservative first-pass quality mask for DESI epoch RV rows."""
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
    missing = sorted(required - set(rows.columns))
    if missing:
        raise KeyError(f"missing columns: {missing}")
    arm_sn = rows[["sn_b", "sn_r", "sn_z"]].max(axis=1)
    return (
        rows["success"].astype(bool)
        & rows["rvs_warn"].eq(0)
        & rows["fiberstatus"].eq(0)
        & np.isfinite(rows["vrad"])
        & np.isfinite(rows["vrad_err"])
        & rows["vrad_err"].gt(0)
        & rows["vrad_err"].le(max_vrad_err)
        & arm_sn.ge(min_arm_sn)
    )
