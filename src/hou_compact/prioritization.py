"""Deterministic DESI file prioritization for bounded private pilot runs."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from hou_compact.desi import gaia_source_id_to_healpix

_DEFAULT_PROGRAM_PRIORITY: Mapping[str, int] = {
    "bright": 0,
    "dark": 1,
    "backup": 2,
}


def prioritize_desi_probe(
    gaia_rows: pd.DataFrame,
    probe_rows: pd.DataFrame,
    *,
    existing_only: bool = True,
    program_priority: Mapping[str, int] = _DEFAULT_PROGRAM_PRIORITY,
) -> pd.DataFrame:
    """Rank DESI files by seed density while keeping backup files last.

    The score is deliberately simple and auditable: files in HEALPix cells containing
    more Gaia seed systems are tried first; ties prefer main bright, then main dark,
    then backup. This maximizes the expected number of matched rows under a hard byte
    and file-count budget without inspecting any candidate-level mass result.

    Only columns used by the ranker are required. Optional provenance columns such as
    ``relative_path``, ``etag``, and ``content_length`` are preserved when present but
    cannot block a valid probe table produced by a leaner file planner.
    """
    if "source_id" not in gaia_rows.columns:
        raise KeyError("gaia_rows has no source_id column")
    required_probe = {"healpix", "survey", "program", "url"}
    missing = sorted(required_probe - set(probe_rows.columns))
    if missing:
        raise KeyError(f"probe_rows is missing columns: {missing}")

    gaia = gaia_rows.copy()
    gaia["healpix"] = [
        gaia_source_id_to_healpix(int(source_id), level=6)
        for source_id in gaia["source_id"]
    ]
    counts = gaia.groupby("healpix")["source_id"].nunique().rename("seed_source_count")

    probe = probe_rows.copy()
    if existing_only:
        if "exists" not in probe.columns:
            raise KeyError("probe_rows has no exists column")
        if pd.api.types.is_bool_dtype(probe["exists"]):
            exists = probe["exists"].fillna(False)
        else:
            exists = probe["exists"].astype(str).str.strip().str.lower().isin(
                {"1", "true", "yes", "y"}
            )
        probe = probe.loc[exists].copy()

    probe["healpix"] = pd.to_numeric(probe["healpix"], errors="raise").astype("int64")
    probe = probe.merge(counts, on="healpix", how="left", validate="many_to_one")
    probe["seed_source_count"] = probe["seed_source_count"].fillna(0).astype("int64")
    probe["program_priority"] = (
        probe["program"].astype(str).map(program_priority).fillna(99).astype("int64")
    )
    probe["survey_priority"] = probe["survey"].astype(str).ne("main").astype("int64")
    probe = probe.sort_values(
        [
            "seed_source_count",
            "survey_priority",
            "program_priority",
            "healpix",
            "survey",
            "program",
        ],
        ascending=[False, True, True, True, True, True],
        kind="stable",
    ).reset_index(drop=True)
    probe.insert(0, "priority_rank", range(1, len(probe) + 1))
    return probe
