from hou_compact.desi_availability_snapshot import (
    MAIN_BACKUP_HEALPIX,
    MAIN_BRIGHT_HEALPIX,
    MAIN_DARK_HEALPIX,
    SNAPSHOT_EXISTING_FILES,
    iter_snapshot_files,
    snapshot_healpix,
    validate_snapshot,
)


def test_snapshot_counts_and_internal_validation() -> None:
    validate_snapshot()
    assert len(MAIN_BRIGHT_HEALPIX) == 236
    assert len(MAIN_DARK_HEALPIX) == 217
    assert len(MAIN_BACKUP_HEALPIX) == 165
    assert len(iter_snapshot_files(include_backup=True)) == SNAPSHOT_EXISTING_FILES
    assert len(iter_snapshot_files()) == 453


def test_nonbackup_snapshot_order_is_bright_then_dark() -> None:
    files = iter_snapshot_files()
    assert files[0].program == "bright"
    assert files[len(MAIN_BRIGHT_HEALPIX) - 1].program == "bright"
    assert files[len(MAIN_BRIGHT_HEALPIX)].program == "dark"
    assert all(item.program != "backup" for item in files)


def test_snapshot_url_matches_documented_layout() -> None:
    item = next(file for file in iter_snapshot_files() if file.healpix == 2063)
    assert item.url.endswith(
        "/rv_output/240521/healpix/main/bright/20/2063/"
        "rvtab_spectra-main-bright-2063.fits"
    )


def test_snapshot_healpix_deduplicates_program_overlap() -> None:
    nonbackup = snapshot_healpix()
    all_programs = snapshot_healpix(include_backup=True)
    assert len(nonbackup) == 265
    assert len(all_programs) == 372
    assert nonbackup.issubset(all_programs)
