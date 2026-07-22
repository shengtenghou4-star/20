import pandas as pd

from hou_compact.prioritization import prioritize_desi_probe


def _source_id_for_healpix(healpix: int, suffix: int = 0) -> int:
    return healpix * 2**47 + suffix


def test_seed_dense_pixels_are_prioritized_with_lean_probe_schema() -> None:
    gaia = pd.DataFrame(
        {
            "source_id": [
                _source_id_for_healpix(10, 1),
                _source_id_for_healpix(10, 2),
                _source_id_for_healpix(20, 1),
            ]
        }
    )
    # This matches the lean schema produced by the current planner/probe pipeline;
    # relative_path is intentionally absent because the ranker never uses it.
    probe = pd.DataFrame(
        {
            "healpix": [20, 10],
            "survey": ["main", "main"],
            "program": ["bright", "bright"],
            "url": ["u20", "u10"],
            "exists": [True, True],
            "content_length": [200, 100],
        }
    )
    ranked = prioritize_desi_probe(gaia, probe)
    assert ranked["healpix"].tolist() == [10, 20]
    assert ranked["seed_source_count"].tolist() == [2, 1]
    assert ranked["priority_rank"].tolist() == [1, 2]
    assert ranked["content_length"].tolist() == [100, 200]


def test_backup_is_ranked_after_bright_and_dark_for_ties() -> None:
    gaia = pd.DataFrame({"source_id": [_source_id_for_healpix(10, 1)]})
    probe = pd.DataFrame(
        {
            "healpix": [10, 10, 10],
            "survey": ["main", "main", "main"],
            "program": ["backup", "dark", "bright"],
            "url": ["ub", "ud", "ur"],
            "exists": [True, True, True],
        }
    )
    ranked = prioritize_desi_probe(gaia, probe)
    assert ranked["program"].tolist() == ["bright", "dark", "backup"]


def test_nonexistent_files_are_removed_by_default() -> None:
    gaia = pd.DataFrame({"source_id": [_source_id_for_healpix(10, 1)]})
    probe = pd.DataFrame(
        {
            "healpix": [10, 10],
            "survey": ["main", "main"],
            "program": ["bright", "dark"],
            "url": ["u1", "u2"],
            "exists": ["true", "false"],
        }
    )
    ranked = prioritize_desi_probe(gaia, probe)
    assert ranked["program"].tolist() == ["bright"]


def test_missing_probe_column_fails_closed() -> None:
    gaia = pd.DataFrame({"source_id": [_source_id_for_healpix(10, 1)]})
    probe = pd.DataFrame({"healpix": [10]})
    try:
        prioritize_desi_probe(gaia, probe)
    except KeyError as error:
        assert "missing columns" in str(error)
    else:
        raise AssertionError("missing probe schema was accepted")
