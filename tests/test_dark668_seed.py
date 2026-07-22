from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hou_compact.dark668 import CATALOGUES


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
    from scripts.prepare_dark668_seed import build_seed

    seed, summary = build_seed(frozen_catalogue_dir, "all", None)
    assert len(seed) == 668
    assert seed["source_id"].is_unique
    assert summary["seed"]["population_counts"] == {"MS": 279, "RGB": 389}
    assert "source_id" not in str(summary)


def test_build_seed_supports_rgb_top_n(frozen_catalogue_dir: Path) -> None:
    from scripts.prepare_dark668_seed import build_seed

    seed, summary = build_seed(frozen_catalogue_dir, "RGB", 25)
    assert len(seed) == 25
    assert seed["population"].eq("RGB").all()
    assert seed["priority_rank"].is_monotonic_increasing
    assert summary["seed"]["rows"] == 25


def test_build_seed_rejects_nonpositive_top(frozen_catalogue_dir: Path) -> None:
    from scripts.prepare_dark668_seed import build_seed

    with pytest.raises(ValueError, match="positive"):
        build_seed(frozen_catalogue_dir, "all", 0)
