"""Candidate-safe positional crossmatching against external reference catalogues.

The module is generic by design: it does not download a particular catalogue and does
not decide that an object is known, novel, compact, or luminous. It propagates Gaia DR3
positions to a common catalogue epoch, records nearest and second-nearest separations,
and fails ambiguous matches closed. Source-level outputs belong in the encrypted evidence
vault when real candidates are evaluated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import astropy.units as u
import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord, match_coordinates_sky
from astropy.time import Time


@dataclass(frozen=True)
class CatalogCrossmatchConfig:
    """Frozen angular and ambiguity gates for one reference catalogue."""

    catalog_epoch_jyear: float = 2000.0
    maximum_separation_arcsec: float = 2.0
    minimum_ambiguity_margin_arcsec: float = 0.2

    def __post_init__(self) -> None:
        if not math.isfinite(self.catalog_epoch_jyear):
            raise ValueError("catalog_epoch_jyear must be finite")
        if (
            not math.isfinite(self.maximum_separation_arcsec)
            or self.maximum_separation_arcsec <= 0
        ):
            raise ValueError("maximum_separation_arcsec must be finite and positive")
        if (
            not math.isfinite(self.minimum_ambiguity_margin_arcsec)
            or self.minimum_ambiguity_margin_arcsec < 0
        ):
            raise ValueError(
                "minimum_ambiguity_margin_arcsec must be finite and non-negative"
            )


def _numeric(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        raise KeyError(f"missing required column {name}")
    values = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
    if np.any(~np.isfinite(values)):
        raise ValueError(f"column {name} contains non-finite values")
    return values


def _optional_numeric(
    frame: pd.DataFrame,
    name: str,
    *,
    default: float,
) -> tuple[np.ndarray, np.ndarray]:
    if name not in frame.columns:
        values = np.full(len(frame), default, dtype=float)
        return values, np.zeros(len(frame), dtype=bool)
    converted = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
    available = np.isfinite(converted)
    values = np.where(available, converted, default)
    return values, available


def propagate_gaia_to_epoch(
    gaia_rows: pd.DataFrame,
    target_epoch_jyear: float,
) -> tuple[SkyCoord, np.ndarray]:
    """Propagate Gaia rows to one Julian-year epoch and report PM availability.

    Missing proper motions are treated as zero only for catalogue navigation and are
    explicitly marked in the returned availability mask. Such rows cannot be described
    as proper-motion-confirmed matches.
    """
    if len(gaia_rows) == 0:
        raise ValueError("gaia_rows must not be empty")
    if not math.isfinite(target_epoch_jyear):
        raise ValueError("target_epoch_jyear must be finite")
    ra = _numeric(gaia_rows, "gaia_ra")
    dec = _numeric(gaia_rows, "gaia_dec")
    ref_epoch, ref_available = _optional_numeric(
        gaia_rows,
        "gaia_ref_epoch",
        default=2016.0,
    )
    pmra, pmra_available = _optional_numeric(gaia_rows, "pmra", default=0.0)
    pmdec, pmdec_available = _optional_numeric(gaia_rows, "pmdec", default=0.0)
    pm_available = ref_available & pmra_available & pmdec_available

    coordinates = SkyCoord(
        ra=ra * u.deg,
        dec=dec * u.deg,
        pm_ra_cosdec=pmra * u.mas / u.yr,
        pm_dec=pmdec * u.mas / u.yr,
        obstime=Time(ref_epoch, format="jyear", scale="tcb"),
        frame="icrs",
    )
    propagated = coordinates.apply_space_motion(
        new_obstime=Time(target_epoch_jyear, format="jyear", scale="tcb")
    )
    return propagated, pm_available


def crossmatch_reference_catalog(
    gaia_rows: pd.DataFrame,
    catalog_rows: pd.DataFrame,
    *,
    config: CatalogCrossmatchConfig = CatalogCrossmatchConfig(),
    catalog_name: str = "reference_catalog",
) -> pd.DataFrame:
    """Match Gaia rows to a reference catalogue with an explicit ambiguity gate."""
    required_gaia = {"source_id", "gaia_ra", "gaia_dec"}
    missing_gaia = sorted(required_gaia - set(gaia_rows.columns))
    if missing_gaia:
        raise KeyError(f"gaia_rows is missing columns: {missing_gaia}")
    required_catalog = {"catalog_id", "ra", "dec"}
    missing_catalog = sorted(required_catalog - set(catalog_rows.columns))
    if missing_catalog:
        raise KeyError(f"catalog_rows is missing columns: {missing_catalog}")
    if gaia_rows.empty:
        return pd.DataFrame(
            columns=[
                "source_id",
                "catalog_name",
                "catalog_id",
                "match_status",
                "match_separation_arcsec",
                "second_match_separation_arcsec",
                "ambiguity_margin_arcsec",
                "proper_motion_propagated",
                "catalog_match_collision_count",
            ]
        )
    if catalog_rows.empty:
        raise ValueError("catalog_rows must not be empty")
    if gaia_rows["source_id"].duplicated().any():
        raise ValueError("gaia_rows contains duplicate source_id rows")
    if catalog_rows["catalog_id"].duplicated().any():
        raise ValueError("catalog_rows contains duplicate catalog_id rows")

    propagated, pm_available = propagate_gaia_to_epoch(
        gaia_rows,
        config.catalog_epoch_jyear,
    )
    catalog = SkyCoord(
        ra=_numeric(catalog_rows, "ra") * u.deg,
        dec=_numeric(catalog_rows, "dec") * u.deg,
        frame="icrs",
        obstime=Time(config.catalog_epoch_jyear, format="jyear", scale="tcb"),
    )
    nearest_index, nearest_sep, _ = match_coordinates_sky(propagated, catalog)
    nearest_arcsec = nearest_sep.to_value(u.arcsec)

    if len(catalog_rows) >= 2:
        _, second_sep, _ = match_coordinates_sky(
            propagated,
            catalog,
            nthneighbor=2,
        )
        second_arcsec = second_sep.to_value(u.arcsec)
        ambiguity_margin = second_arcsec - nearest_arcsec
    else:
        second_arcsec = np.full(len(gaia_rows), np.inf, dtype=float)
        ambiguity_margin = np.full(len(gaia_rows), np.inf, dtype=float)

    within_radius = nearest_arcsec <= config.maximum_separation_arcsec
    unambiguous = ambiguity_margin >= config.minimum_ambiguity_margin_arcsec
    status = np.where(
        ~within_radius,
        "no_match_within_radius",
        np.where(unambiguous, "matched", "ambiguous_nearest_match"),
    )
    matched_catalog_ids = catalog_rows.iloc[nearest_index]["catalog_id"].to_numpy()
    output = pd.DataFrame(
        {
            "source_id": gaia_rows["source_id"].to_numpy(),
            "catalog_name": catalog_name,
            "catalog_id": matched_catalog_ids,
            "match_status": status,
            "match_separation_arcsec": nearest_arcsec,
            "second_match_separation_arcsec": second_arcsec,
            "ambiguity_margin_arcsec": ambiguity_margin,
            "proper_motion_propagated": pm_available,
            "catalog_epoch_jyear": config.catalog_epoch_jyear,
            "maximum_separation_arcsec": config.maximum_separation_arcsec,
            "minimum_ambiguity_margin_arcsec": (
                config.minimum_ambiguity_margin_arcsec
            ),
        }
    )
    accepted = output["match_status"].eq("matched")
    collision_counts = (
        output.loc[accepted, "catalog_id"].value_counts().to_dict()
    )
    output["catalog_match_collision_count"] = [
        int(collision_counts.get(identifier, 0)) if is_accepted else 0
        for identifier, is_accepted in zip(
            output["catalog_id"],
            accepted,
            strict=True,
        )
    ]
    output["match_requires_manual_review"] = (
        output["match_status"].eq("ambiguous_nearest_match")
        | output["catalog_match_collision_count"].gt(1)
        | (~output["proper_motion_propagated"])
    )
    output["interpretation_boundary"] = (
        "A positional association is not proof of identity, prior discovery, compactness, "
        "or physical binarity; source-level matches require manual catalogue validation."
    )
    return output.sort_values("source_id", kind="stable").reset_index(drop=True)
