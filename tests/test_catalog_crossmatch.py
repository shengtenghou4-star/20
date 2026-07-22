import numpy as np
import pandas as pd
import pytest

from hou_compact.catalog_crossmatch import (
    CatalogCrossmatchConfig,
    crossmatch_reference_catalog,
)


def _gaia_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": [1, 2],
            "gaia_ra": [10.0, 20.0],
            "gaia_dec": [0.0, 1.0],
            "gaia_ref_epoch": [2016.0, 2016.0],
            "pmra": [0.0, 0.0],
            "pmdec": [0.0, 0.0],
        }
    )


def test_exact_and_distant_matches_are_separated() -> None:
    catalog = pd.DataFrame(
        {
            "catalog_id": ["known-a", "far"],
            "ra": [10.0, 40.0],
            "dec": [0.0, 0.0],
        }
    )
    result = crossmatch_reference_catalog(
        _gaia_rows(),
        catalog,
        config=CatalogCrossmatchConfig(maximum_separation_arcsec=1.0),
        catalog_name="synthetic",
    )
    first = result.loc[result["source_id"].eq(1)].iloc[0]
    second = result.loc[result["source_id"].eq(2)].iloc[0]
    assert first["match_status"] == "matched"
    assert first["catalog_id"] == "known-a"
    assert first["match_separation_arcsec"] < 1e-8
    assert second["match_status"] == "no_match_within_radius"


def test_ambiguous_nearest_match_fails_closed() -> None:
    gaia = _gaia_rows().iloc[[0]].copy()
    catalog = pd.DataFrame(
        {
            "catalog_id": ["left", "right"],
            "ra": [10.0 - 1.0 / 3600.0, 10.0 + 1.0 / 3600.0],
            "dec": [0.0, 0.0],
        }
    )
    result = crossmatch_reference_catalog(
        gaia,
        catalog,
        config=CatalogCrossmatchConfig(
            maximum_separation_arcsec=2.0,
            minimum_ambiguity_margin_arcsec=0.2,
        ),
    )
    assert result.iloc[0]["match_status"] == "ambiguous_nearest_match"
    assert bool(result.iloc[0]["match_requires_manual_review"])


def test_proper_motion_is_applied_to_catalog_epoch() -> None:
    gaia = pd.DataFrame(
        {
            "source_id": [7],
            "gaia_ra": [10.0],
            "gaia_dec": [0.0],
            "gaia_ref_epoch": [2016.0],
            "pmra": [1000.0],
            "pmdec": [0.0],
        }
    )
    # At Dec=0, 1000 mas/yr for 16 years is 16 arcsec toward smaller RA at J2000.
    catalog = pd.DataFrame(
        {
            "catalog_id": ["mover"],
            "ra": [10.0 - 16.0 / 3600.0],
            "dec": [0.0],
        }
    )
    result = crossmatch_reference_catalog(
        gaia,
        catalog,
        config=CatalogCrossmatchConfig(
            catalog_epoch_jyear=2000.0,
            maximum_separation_arcsec=0.05,
        ),
    )
    assert result.iloc[0]["match_status"] == "matched"
    assert bool(result.iloc[0]["proper_motion_propagated"])
    assert result.iloc[0]["match_separation_arcsec"] < 0.01


def test_missing_proper_motion_is_marked_for_manual_review() -> None:
    gaia = _gaia_rows().iloc[[0]].drop(columns=["pmra", "pmdec"])
    catalog = pd.DataFrame(
        {"catalog_id": ["static"], "ra": [10.0], "dec": [0.0]}
    )
    result = crossmatch_reference_catalog(gaia, catalog)
    assert result.iloc[0]["match_status"] == "matched"
    assert not bool(result.iloc[0]["proper_motion_propagated"])
    assert bool(result.iloc[0]["match_requires_manual_review"])


def test_catalog_collision_is_flagged() -> None:
    gaia = pd.DataFrame(
        {
            "source_id": [1, 2],
            "gaia_ra": [10.0, 10.0 + 0.1 / 3600.0],
            "gaia_dec": [0.0, 0.0],
            "gaia_ref_epoch": [2016.0, 2016.0],
            "pmra": [0.0, 0.0],
            "pmdec": [0.0, 0.0],
        }
    )
    catalog = pd.DataFrame(
        {"catalog_id": ["shared"], "ra": [10.0], "dec": [0.0]}
    )
    result = crossmatch_reference_catalog(
        gaia,
        catalog,
        config=CatalogCrossmatchConfig(maximum_separation_arcsec=1.0),
    )
    assert result["catalog_match_collision_count"].tolist() == [2, 2]
    assert result["match_requires_manual_review"].tolist() == [True, True]


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        CatalogCrossmatchConfig(maximum_separation_arcsec=0.0)
