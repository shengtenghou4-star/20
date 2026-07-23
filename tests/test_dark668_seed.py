from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest

from hou_compact.dark668 import CATALOGUES


def _seed_script() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "prepare_dark668_seed.py"
    spec = importlib.util.spec_from_file_location("prepare_dark668_seed", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load prepare_dark668_seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {
            nested
            for child in value.values()
            for nested in _all_keys(child)
        }
    if isinstance(value, list):
        return {nested for child in value for nested in _all_keys(child)}
    return set()


@pytest.fixture
def frozen_catalogue_dir(tmp_path: Path) -> Path:
    for spec in CATALOGUES:
        count = spec.expected_promising_count
        prefix = "1" if spec.population == "RGB" else "2"
        frame = pd.DataFrame(
            {
                "source_id": [f"{prefix}{index:018d}" for index in range(count)],
                "ra": [float(index % 360) for index in range(count)],
                "dec": [float(index % 90) for index in range(count)],
                "parallax": [2.0 + 0.001 * index for index in range(count)],
                "parallax_error": [0.1] * count,
                "phot_g_mean_mag": [11.0 + 0.001 * index for index in range(count)],
                "ruwe": [2.0] * count,
                "rv_amplitude_robust": [20.0] * count,
                "rv_nb_transits": [20 + index % 5 for index in range(count)],
                "mass": [1.0] * count,
                "radius": [4.0 if spec.population == "RGB" else 1.0] * count,
                "fit_period": [300.0 + index for index in range(count)],
                "fit_period_errup": [10.0] * count,
                "fit_period_errlow": [10.0] * count,
                "fit_companion_mass": [4.0 + 0.01 * index for index in range(count)],
                "fit_companion_mass_errup": [0.5] * count,
                "fit_companion_mass_errlow": [0.4] * count,
                "mass_significance": [
                    0.8 + index / (10 * count) for index in range(count)
                ],
                "flag_quality": [True] * count,
            }
        )
        frame.to_csv(tmp_path / spec.filename, index=False)
    return tmp_path


def test_build_seed_preserves_exact_population_counts(
    frozen_catalogue_dir: Path,
) -> None:
    build_seed = _seed_script().build_seed
    seed, summary = build_seed(frozen_catalogue_dir, "all", None)
    assert len(seed) == 668
    assert seed["source_id"].is_unique
    assert {"mass", "radius"}.issubset(seed.columns)
    assert seed["mass"].notna().all()
    assert seed["radius"].notna().all()
    assert summary["seed"]["population_counts"] == {"MS": 279, "RGB": 389}
    assert {"source_id", "ra", "dec", "mass", "radius"}.isdisjoint(
        _all_keys(summary)
    )


def test_build_seed_supports_rgb_top_n(frozen_catalogue_dir: Path) -> None:
    build_seed = _seed_script().build_seed
    seed, summary = build_seed(frozen_catalogue_dir, "RGB", 25)
    assert len(seed) == 25
    assert seed["population"].eq("RGB").all()
    assert seed["priority_rank"].is_monotonic_increasing
    assert summary["seed"]["rows"] == 25


def test_build_seed_rejects_nonpositive_top(frozen_catalogue_dir: Path) -> None:
    build_seed = _seed_script().build_seed
    with pytest.raises(ValueError, match="positive"):
        build_seed(frozen_catalogue_dir, "all", 0)
