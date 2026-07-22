from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits

from hou_compact.desi_epoch_columns import restore_single_exposure_columns


def _write_official_epoch_file(path: Path, *, mismatch: bool = False) -> None:
    rvtab = np.array(
        [
            (10, 100, 5.0, 6.0, 7.0),
            (11, 101, 8.0, 9.0, 10.0),
        ],
        dtype=[
            ("TARGETID", "i8"),
            ("EXPID", "i4"),
            ("SN_B", "f8"),
            ("SN_R", "f8"),
            ("SN_Z", "f8"),
        ],
    )
    fibermap = np.array(
        [
            (999 if mismatch else 10, 100, 59000.25, 20200101),
            (11, 101, 59001.50, 20200102),
        ],
        dtype=[
            ("TARGETID", "i8"),
            ("EXPID", "i4"),
            ("MJD", "f8"),
            ("NIGHT", "i4"),
        ],
    )
    fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.BinTableHDU(rvtab, name="RVTAB"),
            fits.BinTableHDU(fibermap, name="FIBERMAP"),
        ]
    ).writeto(path)


def test_restore_uses_fibermap_time_and_rvtab_signal_to_noise(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-bright-1.fits"
    _write_official_epoch_file(path)
    extracted = pd.DataFrame(
        {
            "source_id": [222, 111],
            "targetid": [11, 10],
            "expid": [101, 100],
            "mjd": [np.nan, np.nan],
            "sn_b": [np.nan, np.nan],
            "sn_r": [np.nan, np.nan],
            "sn_z": [np.nan, np.nan],
        }
    )

    restored = restore_single_exposure_columns(path, extracted)

    assert restored["source_id"].tolist() == [222, 111]
    assert restored["mjd"].tolist() == [59001.50, 59000.25]
    assert restored["night"].tolist() == [20200102, 20200101]
    assert restored["sn_b"].tolist() == [8.0, 5.0]
    assert restored["sn_r"].tolist() == [9.0, 6.0]
    assert restored["sn_z"].tolist() == [10.0, 7.0]
    assert restored["official_epoch_columns_restored"].tolist() == [True, True]


def test_restore_rejects_rvtab_fibermap_alignment_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.fits"
    _write_official_epoch_file(path, mismatch=True)
    extracted = pd.DataFrame({"targetid": [10], "expid": [100]})
    with pytest.raises(ValueError, match="TARGETID"):
        restore_single_exposure_columns(path, extracted)


def test_restore_rejects_unmatched_extracted_row(tmp_path: Path) -> None:
    path = tmp_path / "official.fits"
    _write_official_epoch_file(path)
    extracted = pd.DataFrame({"targetid": [999], "expid": [999]})
    with pytest.raises(ValueError, match="could not be matched"):
        restore_single_exposure_columns(path, extracted)


def test_restore_empty_frame_preserves_schema(tmp_path: Path) -> None:
    path = tmp_path / "unused.fits"
    frame = pd.DataFrame(columns=["targetid", "expid"])
    restored = restore_single_exposure_columns(path, frame)
    assert restored.empty
    assert set(["mjd", "night", "sn_b", "sn_r", "sn_z"]).issubset(restored.columns)
