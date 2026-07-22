"""Deterministic ingestion and candidate-safe ranking for the Dark-668 catalogue.

The source catalogues are public, but source-level rankings are treated as
novelty-sensitive research products. This module therefore separates exact
catalogue validation from candidate-safe aggregate reporting.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Literal
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

Population = Literal["RGB", "MS"]

ZENODO_RECORD = "19181131"
ZENODO_DOI = "10.5281/zenodo.19181131"


@dataclass(frozen=True)
class CatalogueSpec:
    population: Population
    filename: str
    md5: str
    expected_promising_count: int

    @property
    def url(self) -> str:
        encoded = self.filename.replace("+", "%2B")
        return f"https://zenodo.org/records/{ZENODO_RECORD}/files/{encoded}?download=1"


CATALOGUES: tuple[CatalogueSpec, ...] = (
    CatalogueSpec(
        population="RGB",
        filename="RGB+BH_candidates_from_GaiaDR3_summary_diagnostics.csv",
        md5="000dac405ed9e75d28f7c47d206ec345",
        expected_promising_count=389,
    ),
    CatalogueSpec(
        population="MS",
        filename="MS+BH_candidates_from_GaiaDR3_summary_diagnostics.csv",
        md5="07eb6acff1f98d3a656741f2e61daed3",
        expected_promising_count=279,
    ),
)

REQUIRED_COLUMNS = {
    "source_id",
    "ra",
    "dec",
    "parallax",
    "parallax_error",
    "phot_g_mean_mag",
    "ruwe",
    "rv_amplitude_robust",
    "rv_nb_transits",
    "mass",
    "radius",
    "fit_period",
    "fit_period_errup",
    "fit_period_errlow",
    "fit_companion_mass",
    "fit_companion_mass_errup",
    "fit_companion_mass_errlow",
    "mass_significance",
    "flag_quality",
}


def file_md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - upstream publishes MD5 for identity checking
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_catalogue(
    spec: CatalogueSpec,
    destination: Path,
    *,
    timeout: float = 120.0,
    overwrite: bool = False,
) -> dict[str, object]:
    """Download one frozen Zenodo file and verify its published checksum."""

    destination = Path(destination)
    if destination.exists() and not overwrite:
        observed = file_md5(destination)
        if observed != spec.md5:
            raise ValueError(
                f"existing file checksum mismatch for {destination}: {observed} != {spec.md5}"
            )
        return {
            "population": spec.population,
            "path": str(destination),
            "bytes": destination.stat().st_size,
            "md5": observed,
            "downloaded": False,
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = Request(
        spec.url,
        headers={"User-Agent": "HOU-COMPACT/0.1 Dark-668 catalogue acquisition"},
    )
    try:
        with urlopen(request, timeout=timeout) as response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        observed = file_md5(temporary)
        if observed != spec.md5:
            raise ValueError(
                f"downloaded checksum mismatch for {spec.filename}: {observed} != {spec.md5}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "population": spec.population,
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "md5": spec.md5,
        "downloaded": True,
    }


def _coerce_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    normalized = series.astype("string").str.strip().str.lower()
    mapping = {
        "true": True,
        "t": True,
        "1": True,
        "yes": True,
        "false": False,
        "f": False,
        "0": False,
        "no": False,
    }
    result = normalized.map(mapping)
    if result.isna().any():
        bad = sorted(normalized[result.isna()].dropna().unique().tolist())[:10]
        raise ValueError(f"unrecognized boolean values: {bad}")
    return result.astype(bool)


def load_catalogue(path: Path, population: Population) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"catalogue missing required columns: {sorted(missing)}")
    frame = frame.copy()
    frame["population"] = population
    frame["flag_quality"] = _coerce_bool(frame["flag_quality"])
    frame["source_id"] = frame["source_id"].astype("string")
    if frame["source_id"].isna().any() or frame["source_id"].duplicated().any():
        raise ValueError("source_id must be present and unique within each catalogue")
    return frame


def promising_subset(frame: pd.DataFrame) -> pd.DataFrame:
    mass = pd.to_numeric(frame["fit_companion_mass"], errors="coerce")
    mask = frame["flag_quality"].astype(bool) & mass.gt(3.0)
    return frame.loc[mask].copy()


def validate_catalogue(frame: pd.DataFrame, spec: CatalogueSpec) -> dict[str, object]:
    promising = promising_subset(frame)
    count = int(len(promising))
    if count != spec.expected_promising_count:
        raise ValueError(
            f"{spec.population} promising-count drift: {count} != "
            f"{spec.expected_promising_count}"
        )
    return {
        "population": spec.population,
        "rows": int(len(frame)),
        "promising_rows": count,
        "expected_promising_rows": spec.expected_promising_count,
        "source_ids_unique": bool(frame["source_id"].is_unique),
    }


def _robust_percentile(series: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    rank = numeric.rank(method="average", pct=True)
    if not higher_is_better:
        rank = 1.0 - rank
    return rank.fillna(0.0).clip(0.0, 1.0)


def rank_promising_targets(frame: pd.DataFrame) -> pd.DataFrame:
    """Rank public candidates for follow-up without assigning object classes.

    The score prioritizes high posterior mass support, bright/nearby primaries,
    more Gaia RV transits, and tighter relative mass/period constraints. RGB
    candidates receive a modest reliability prior because the source paper
    treats them as less confounded than the supplementary main-sequence sample.
    """

    ranked = promising_subset(frame)
    if ranked.empty:
        return ranked.assign(followup_score=pd.Series(dtype=float))

    mass = pd.to_numeric(ranked["fit_companion_mass"], errors="coerce")
    mass_low = mass - pd.to_numeric(ranked["fit_companion_mass_errlow"], errors="coerce").abs()
    mass_unc = 0.5 * (
        pd.to_numeric(ranked["fit_companion_mass_errup"], errors="coerce").abs()
        + pd.to_numeric(ranked["fit_companion_mass_errlow"], errors="coerce").abs()
    )
    period = pd.to_numeric(ranked["fit_period"], errors="coerce").abs()
    period_unc = 0.5 * (
        pd.to_numeric(ranked["fit_period_errup"], errors="coerce").abs()
        + pd.to_numeric(ranked["fit_period_errlow"], errors="coerce").abs()
    )
    relative_mass_unc = mass_unc / mass.replace(0.0, np.nan)
    relative_period_unc = period_unc / period.replace(0.0, np.nan)
    parallax_snr = (
        pd.to_numeric(ranked["parallax"], errors="coerce")
        / pd.to_numeric(ranked["parallax_error"], errors="coerce").replace(0.0, np.nan)
    )

    components = pd.DataFrame(index=ranked.index)
    components["mass_significance_score"] = _robust_percentile(ranked["mass_significance"])
    components["mass_lower_bound_score"] = _robust_percentile(mass_low)
    components["brightness_score"] = _robust_percentile(
        ranked["phot_g_mean_mag"], higher_is_better=False
    )
    components["parallax_snr_score"] = _robust_percentile(parallax_snr)
    components["rv_transit_score"] = _robust_percentile(ranked["rv_nb_transits"])
    components["mass_precision_score"] = _robust_percentile(
        relative_mass_unc, higher_is_better=False
    )
    components["period_precision_score"] = _robust_percentile(
        relative_period_unc, higher_is_better=False
    )
    components["population_prior"] = ranked["population"].eq("RGB").astype(float)

    weights = {
        "mass_significance_score": 0.24,
        "mass_lower_bound_score": 0.18,
        "brightness_score": 0.14,
        "parallax_snr_score": 0.12,
        "rv_transit_score": 0.10,
        "mass_precision_score": 0.09,
        "period_precision_score": 0.07,
        "population_prior": 0.06,
    }
    ranked["followup_score"] = sum(components[name] * weight for name, weight in weights.items())
    ranked["mass_lower_bound_proxy"] = mass_low
    ranked["relative_mass_uncertainty"] = relative_mass_unc
    ranked["relative_period_uncertainty"] = relative_period_unc
    ranked["parallax_snr"] = parallax_snr
    ranked = ranked.sort_values(
        ["followup_score", "mass_significance", "fit_companion_mass"],
        ascending=[False, False, False],
        kind="mergesort",
    ).reset_index(drop=True)
    ranked.insert(0, "priority_rank", np.arange(1, len(ranked) + 1, dtype=int))
    return ranked


def candidate_safe_summary(ranked: pd.DataFrame) -> dict[str, object]:
    """Return aggregates only; never include source identifiers or coordinates."""

    if ranked.empty:
        return {"rows": 0, "population_counts": {}, "score_quantiles": {}}
    quantiles = ranked["followup_score"].quantile([0.0, 0.25, 0.5, 0.75, 1.0])
    return {
        "rows": int(len(ranked)),
        "population_counts": {
            str(key): int(value)
            for key, value in ranked["population"].value_counts().sort_index().items()
        },
        "score_quantiles": {f"q{int(q * 100):02d}": float(value) for q, value in quantiles.items()},
        "mass_lower_bound_proxy_ge_3_count": int(
            pd.to_numeric(ranked["mass_lower_bound_proxy"], errors="coerce").ge(3.0).sum()
        ),
        "claim_boundary": (
            "Aggregate follow-up prioritization only. No row is classified as a compact object, "
            "black hole, neutron star, or confirmed binary."
        ),
    }
