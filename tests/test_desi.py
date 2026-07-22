from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits

from hou_compact.desi import (
    clean_epoch_mask,
    desi_healpix_parent,
    extract_single_epoch_rows,
    gaia_source_id_to_healpix,
    plan_single_epoch_files,
)


def test_gaia_source_id_healpix_decoding() -> None:
    hp12 = 123_456_789
    source_id = hp12 * 2**35 + 17
    assert gaia_source_id_to_healpix(source_id, level=12) == hp12
    assert gaia_source_id_to_healpix(source_id, level=6) == hp12 // 4**6


def test_desi_path_matches_documented_layout() -> None:
    source_id = 2152 * 2**47 + 1
    target = plan_single_epoch_files(
        [source_id],
        survey_programs=(("cmx", "other"),),
    )[0]
    assert target.healpix == 2152
    assert desi_healpix_parent(2152) == 21
    assert target.url.endswith(
        "healpix/cmx/other/21/2152/rvtab_spectra-cmx-other-2152.fits"
    )


def test_file_plan_is_deterministic() -> None:
    sid_a = 100 * 2**47 + 1
    sid_b = 101 * 2**47 + 2
    plan = plan_single_epoch_files(
        [sid_b, sid_a, sid_a],
        survey_programs=(("main", "bright"), ("main", "dark")),
    )
    assert [(item.healpix, item.program) for item in plan] == [
        (100, "bright"),
        (100, "dark"),
        (101, "bright"),
        (101, "dark"),
    ]


def _write_mock_desi_file(path: Path, mismatch: bool = False) -> None:
    rvtab = np.array(
        [
            (10, 100, 59000.0, 4.0, 0.5, 0, True, 2152),
            (11, 101, 59001.0, 8.0, 1.0, 0, True, 2152),
        ],
        dtype=[
            ("TARGETID", "i8"),
            ("EXPID", "i4"),
            ("MJD", "f8"),
            ("VRAD", "f8"),
            ("VRAD_ERR", "f8"),
            ("RVS_WARN", "i8"),
            ("SUCCESS", "?"),
            ("HEALPIX", "i8"),
        ],
    )
    fibermap = np.array(
        [
            (999 if mismatch else 10, 0, 111),
            (11, 0, 222),
        ],
        dtype=[
            ("TARGETID", "i8"),
            ("FIBERSTATUS", "i4"),
            ("GAIA_DR3_SOURCE_ID", "i8"),
        ],
    )
    scores = np.array(
        [(5.0, 3.0, 2.0), (1.0, 1.0, 1.0)],
        dtype=[
            ("MEDIAN_COADD_SNR_B", "f8"),
            ("MEDIAN_COADD_SNR_R", "f8"),
            ("MEDIAN_COADD_SNR_Z", "f8"),
        ],
    )
    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.BinTableHDU(rvtab, name="RVTAB"),
            fits.BinTableHDU(fibermap, name="FIBERMAP"),
            fits.BinTableHDU(scores, name="SCORES"),
        ]
    ).writeto(path)


def test_extract_rows_and_quality_mask(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-cmx-other-2152.fits"
    _write_mock_desi_file(path)
    rows = extract_single_epoch_rows(
        path,
        [111, 333],
        survey="cmx",
        program="other",
    )
    assert rows["source_id"].tolist() == [111]
    assert rows["source_match_mode"].tolist() == ["direct_dr3_source_id"]
    assert clean_epoch_mask(rows).tolist() == [True]


def test_extract_rejects_targetid_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-cmx-other-2152.fits"
    _write_mock_desi_file(path, mismatch=True)
    with pytest.raises(ValueError, match="TARGETID"):
        extract_single_epoch_rows(
            path,
            [111],
            survey="cmx",
            program="other",
        )


def test_clean_mask_rejects_weak_epoch() -> None:
    rows = pd.DataFrame(
        {
            "success": [True],
            "rvs_warn": [0],
            "fiberstatus": [0],
            "vrad": [1.0],
            "vrad_err": [1.0],
            "sn_b": [1.0],
            "sn_r": [1.0],
            "sn_z": [1.0],
        }
    )
    assert clean_epoch_mask(rows).tolist() == [False]
