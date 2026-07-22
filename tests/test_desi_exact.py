from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits

from hou_compact.desi_exact import (
    extract_single_epoch_rows_by_dr2_refid,
    extract_single_epoch_rows_by_targetid,
)


def _write_exact_file(path: Path, *, mismatch: bool = False) -> None:
    rvtab = np.array(
        [
            (101, 1, 59000.0, 12.0, 0.5, True, 0),
            (202, 2, 59001.0, -8.0, 0.8, True, 0),
            (999, 3, 59002.0, 1.0, 5.0, False, 1),
        ],
        dtype=[
            ("TARGETID", "i8"),
            ("EXPID", "i8"),
            ("MJD", "f8"),
            ("VRAD", "f8"),
            ("VRAD_ERR", "f8"),
            ("SUCCESS", "?"),
            ("RVS_WARN", "i8"),
        ],
    )
    fibermap = np.array(
        [
            (404 if mismatch else 101, 1, 0, 111, "G2"),
            (202, 2, 0, 222, "G2"),
            (999, 3, 0, 333, "T2"),
        ],
        dtype=[
            ("TARGETID", "i8"),
            ("EXPID", "i8"),
            ("FIBERSTATUS", "i8"),
            ("REF_ID", "i8"),
            ("REF_CAT", "U2"),
        ],
    )
    scores = np.array(
        [(10.0, 11.0, 12.0), (5.0, 6.0, 7.0), (1.0, 1.0, 1.0)],
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


def test_exact_targetid_mapping_extracts_only_official_matches(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-bright-10.fits"
    _write_exact_file(path)
    mapping = pd.DataFrame(
        {
            "source_id": [1001, 2002],
            "targetid": [101, 202],
            "match_distance_arcsec": [0.1, 0.4],
        }
    )
    rows = extract_single_epoch_rows_by_targetid(
        path,
        mapping,
        survey="main",
        program="bright",
        healpix=10,
    )
    assert rows["source_id"].tolist() == [1001, 2002]
    assert rows["targetid"].tolist() == [101, 202]
    assert rows["source_match_mode"].unique().tolist() == [
        "official_datalab_zpix_targetid"
    ]
    assert rows["source_match_separation_arcsec"].tolist() == [0.1, 0.4]
    assert rows["vrad"].tolist() == [12.0, -8.0]


def test_dr2_bridge_refid_mapping_recovers_exact_rows(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-bright-10.fits"
    _write_exact_file(path)
    bridge = pd.DataFrame(
        {
            "source_id": [1001, 2002, 3003],
            "dr2_source_id": [111, 222, 333],
            "dr2_bridge_status": [
                "accepted_unique_or_separated_nearest",
                "accepted_unique_or_separated_nearest",
                "accepted_unique_or_separated_nearest",
            ],
            "dr2_angular_distance_mas": [2.0, 4.0, 1.0],
            "dr2_neighbour_count": [1, 2, 1],
            "dr2_distance_margin_mas": [np.inf, 12.0, np.inf],
        }
    )
    rows = extract_single_epoch_rows_by_dr2_refid(
        path,
        bridge,
        survey="main",
        program="bright",
        healpix=10,
    )
    assert rows["source_id"].tolist() == [1001, 2002]
    assert rows["targetid"].tolist() == [101, 202]
    assert rows["desi_ref_id"].tolist() == [111, 222]
    assert rows["source_match_mode"].unique().tolist() == [
        "gaia_dr3_dr2_neighbourhood_ref_id"
    ]
    assert rows["source_match_separation_arcsec"].tolist() == [0.002, 0.004]
    assert rows["dr2_neighbour_count"].tolist() == [1, 2]


def test_rejected_dr2_bridge_rows_are_not_used(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-dark-10.fits"
    _write_exact_file(path)
    bridge = pd.DataFrame(
        {
            "source_id": [1001],
            "dr2_source_id": [111],
            "dr2_bridge_status": ["rejected_ambiguous_nearest"],
            "dr2_angular_distance_mas": [2.0],
            "dr2_neighbour_count": [2],
            "dr2_distance_margin_mas": [1.0],
        }
    )
    rows = extract_single_epoch_rows_by_dr2_refid(
        path,
        bridge,
        survey="main",
        program="dark",
        healpix=10,
    )
    assert rows.empty


def test_exact_target_conflict_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-dark-10.fits"
    _write_exact_file(path)
    mapping = pd.DataFrame(
        {
            "source_id": [1001, 2002],
            "targetid": [101, 101],
            "match_distance_arcsec": [0.1, 0.2],
        }
    )
    with pytest.raises(ValueError, match="multiple Gaia sources"):
        extract_single_epoch_rows_by_targetid(
            path,
            mapping,
            survey="main",
            program="dark",
            healpix=10,
        )


def test_dr2_bridge_conflict_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "rvtab_spectra-main-dark-10.fits"
    _write_exact_file(path)
    bridge = pd.DataFrame(
        {
            "source_id": [1001, 2002],
            "dr2_source_id": [111, 111],
            "dr2_bridge_status": [
                "accepted_unique_or_separated_nearest",
                "accepted_unique_or_separated_nearest",
            ],
            "dr2_angular_distance_mas": [2.0, 3.0],
            "dr2_neighbour_count": [1, 1],
            "dr2_distance_margin_mas": [np.inf, np.inf],
        }
    )
    with pytest.raises(ValueError, match="multiple DR3 sources"):
        extract_single_epoch_rows_by_dr2_refid(
            path,
            bridge,
            survey="main",
            program="dark",
            healpix=10,
        )


def test_exact_extractor_rejects_row_misalignment(tmp_path: Path) -> None:
    path = tmp_path / "bad.fits"
    _write_exact_file(path, mismatch=True)
    mapping = pd.DataFrame(
        {"source_id": [1001], "targetid": [101], "match_distance_arcsec": [0.1]}
    )
    with pytest.raises(ValueError, match="TARGETID rows are not aligned"):
        extract_single_epoch_rows_by_targetid(
            path,
            mapping,
            survey="main",
            program="bright",
            healpix=10,
        )


def test_exact_extractor_returns_empty_for_no_targetid_overlap(tmp_path: Path) -> None:
    path = tmp_path / "none.fits"
    _write_exact_file(path)
    mapping = pd.DataFrame(
        {"source_id": [42], "targetid": [404], "match_distance_arcsec": [0.2]}
    )
    rows = extract_single_epoch_rows_by_targetid(
        path,
        mapping,
        survey="main",
        program="bright",
        healpix=10,
    )
    assert rows.empty
