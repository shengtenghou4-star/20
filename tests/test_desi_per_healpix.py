from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits

from hou_compact.desi import extract_single_epoch_rows


def _table_hdu(name: str, columns: dict[str, np.ndarray]) -> fits.BinTableHDU:
    return fits.BinTableHDU.from_columns(
        [fits.Column(name=key, array=value, format=_format(value)) for key, value in columns.items()],
        name=name,
    )


def _format(value: np.ndarray) -> str:
    if value.dtype.kind in {"i", "u"}:
        return "K"
    if value.dtype.kind == "b":
        return "L"
    if value.dtype.kind == "f":
        return "D"
    width = max(int(value.dtype.itemsize), 1)
    return f"{width}A"


def _write_per_healpix(path: Path, *, include_gaia: bool = False) -> None:
    rvtab = _table_hdu(
        "RVTAB",
        {
            "TARGETID": np.array([101, 102], dtype=np.int64),
            "EXPID": np.array([11, 12], dtype=np.int64),
            "MJD": np.array([59000.0, 59001.0]),
            "VRAD": np.array([30.0, 40.0]),
            "VRAD_ERR": np.array([1.0, 2.0]),
            "SUCCESS": np.array([True, True]),
            "RVS_WARN": np.array([0, 0], dtype=np.int64),
        },
    )
    fibermap = _table_hdu(
        "FIBERMAP",
        {
            "TARGETID": np.array([101, 102], dtype=np.int64),
            "EXPID": np.array([11, 12], dtype=np.int64),
            "TARGET_RA": np.array([10.0, 20.0]),
            "TARGET_DEC": np.array([5.0, -5.0]),
            "REF_EPOCH": np.array([2016.0, 2016.0]),
            "REF_ID": np.array([9001, 9002], dtype=np.int64),
            "REF_CAT": np.array(["G2", "G2"]),
            "FIBERSTATUS": np.array([0, 0], dtype=np.int64),
        },
    )
    scores = _table_hdu(
        "SCORES",
        {
            "MEDIAN_COADD_SNR_B": np.array([5.0, 6.0]),
            "MEDIAN_COADD_SNR_R": np.array([7.0, 8.0]),
            "MEDIAN_COADD_SNR_Z": np.array([9.0, 10.0]),
        },
    )
    hdus: list[fits.hdu.base.ExtensionHDU] = [
        fits.PrimaryHDU(),
        rvtab,
        fibermap,
        scores,
    ]
    if include_gaia:
        hdus.append(
            _table_hdu(
                "GAIA",
                {"SOURCE_ID": np.array([1234, 5678], dtype=np.int64)},
            )
        )
    fits.HDUList(hdus).writeto(path)


def test_per_healpix_file_without_gaia_hdu_uses_position_and_proper_motion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rvtab_spectra-main-bright-123.fits"
    _write_per_healpix(path)
    sources = pd.DataFrame(
        {
            "source_id": [1234],
            "gaia_ra": [10.0],
            "gaia_dec": [5.0],
            "gaia_ref_epoch": [2016.0],
            "pmra": [0.0],
            "pmdec": [0.0],
        }
    )
    result = extract_single_epoch_rows(
        path,
        sources,
        survey="main",
        program="bright",
        healpix=123,
    )
    assert len(result) == 1
    row = result.iloc[0]
    assert row["source_id"] == 1234
    assert row["targetid"] == 101
    assert row["healpix"] == 123
    assert row["source_match_mode"] == "position_proper_motion"
    assert row["source_match_separation_arcsec"] < 1e-8
    assert row["desi_ref_id"] == 9001


def test_per_healpix_position_match_rejects_distant_rows(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-dark-456.fits"
    _write_per_healpix(path)
    sources = pd.DataFrame(
        {
            "source_id": [1234],
            "gaia_ra": [11.0],
            "gaia_dec": [5.0],
        }
    )
    result = extract_single_epoch_rows(
        path,
        sources,
        survey="main",
        program="dark",
        healpix=456,
    )
    assert result.empty
    assert "source_match_mode" in result.columns


def test_legacy_source_ids_require_direct_dr3_column(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-bright-789.fits"
    _write_per_healpix(path)
    with pytest.raises(KeyError, match="pass a Gaia source DataFrame"):
        extract_single_epoch_rows(
            path,
            {1234},
            survey="main",
            program="bright",
            healpix=789,
        )


def test_combined_file_with_gaia_hdu_keeps_direct_source_id_mode(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-bright-321.fits"
    _write_per_healpix(path, include_gaia=True)
    result = extract_single_epoch_rows(
        path,
        {5678},
        survey="main",
        program="bright",
        healpix=321,
    )
    assert len(result) == 1
    assert result.iloc[0]["source_id"] == 5678
    assert result.iloc[0]["source_match_mode"] == "direct_dr3_source_id"
    assert np.isnan(result.iloc[0]["source_match_separation_arcsec"])


def test_ambiguous_close_sources_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-bright-654.fits"
    _write_per_healpix(path)
    sources = pd.DataFrame(
        {
            "source_id": [1, 2],
            "gaia_ra": [10.0, 10.00001],
            "gaia_dec": [5.0, 5.0],
        }
    )
    result = extract_single_epoch_rows(
        path,
        sources,
        survey="main",
        program="bright",
        healpix=654,
        minimum_ambiguity_margin_arcsec=0.1,
    )
    assert result.empty
