from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from astropy.table import Table

CAPSULE = Path(__file__).resolve().parents[1] / "capsules" / "hou_compact_final" / "hou_compact"
sys.path.insert(0, str(CAPSULE))

from gaia_covariance_enrichment import augment_candidate_covariance_fields  # noqa: E402
from gaia_covariance_vetting import augment_covariance_phase_products  # noqa: E402
from hou_compact.reference_covariance import _nsstools_frame  # noqa: E402


def test_serialized_corr_vec_becomes_numeric_for_reference_package() -> None:
    frame = _nsstools_frame(
        {
            "source_id": "1234567890123456789",
            "nss_solution_type": "SB1C",
            "corr_vec": "[0.1,NaN,0.2,0.3,0.4,0.5]",
            "period": 10.0,
            "period_error": 0.1,
            "center_of_mass_velocity": 5.0,
            "center_of_mass_velocity_error": 0.5,
            "semi_amplitude_primary": 150.0,
            "semi_amplitude_primary_error": 1.0,
            "t_periastron": 100.0,
            "t_periastron_error": 0.2,
        },
        (
            "period",
            "center_of_mass_velocity",
            "semi_amplitude_primary",
            "t_periastron",
        ),
    )
    vector = frame.iloc[0]["corr_vec"]
    assert isinstance(vector, np.ndarray)
    assert vector.shape == (6,)
    assert np.isnan(vector[1])
    assert vector[5] == 0.5


def test_covariance_gate_is_deterministic_candidate_safe_and_monotonic() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        source_a = "1234567890123456789"
        source_b = "3234567890123456789"
        corr_values = np.zeros((2, 231), dtype=float)
        corr_mask = np.ones((2, 231), dtype=bool)
        corr_values[:, :6] = np.asarray(
            [
                [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
                [0.02, 0.03, 0.04, 0.05, 0.06, 0.07],
            ]
        )
        corr_mask[:, :6] = False
        corr_vec = np.ma.masked_array(corr_values, mask=corr_mask)
        gaia_ecsv = directory / "gaia.ecsv"
        Table(
            {
                "source_id": [int(source_a), int(source_b)],
                "nss_solution_type": ["SB1C", "SB1C"],
                "bit_index": [31, 31],
                "corr_vec": corr_vec,
                "period": [10.0, 20.0],
                "period_error": [0.1, 0.2],
                "center_of_mass_velocity": [5.0, -10.0],
                "center_of_mass_velocity_error": [0.5, 1.0],
                "semi_amplitude_primary": [150.0, 30.0],
                "semi_amplitude_primary_error": [1.0, 2.0],
                "eccentricity": [0.0, 0.0],
                "eccentricity_error": [0.0, 0.0],
                "arg_periastron": [0.0, 0.0],
                "arg_periastron_error": [0.0, 0.0],
                "t_periastron": [100.0, 200.0],
                "t_periastron_error": [0.2, 0.3],
                "mass_flame_lower": [1.0, 0.9],
            }
        ).write(gaia_ecsv, format="ascii.ecsv", overwrite=True)

        candidate_gaia = directory / "candidate_gaia.csv"
        candidate_gaia.write_text(
            "source_id,nss_solution_type,period,period_error,semi_amplitude_primary,"
            "semi_amplitude_primary_error,eccentricity,eccentricity_error,mass_flame_lower\n"
            f"{source_a},SB1C,10,0.1,150,1,0,0,1.0\n"
            f"{source_b},SB1C,20,0.2,30,2,0,0,0.9\n",
            encoding="utf-8",
        )
        enrichment = augment_candidate_covariance_fields(
            gaia_ecsv=gaia_ecsv,
            candidate_gaia=candidate_gaia,
        )
        assert enrichment["candidate_sources"] == 2
        assert enrichment["corr_vec_serialization"] == (
            "flat JSON numeric array with NaN padding"
        )
        with candidate_gaia.open("r", encoding="utf-8", newline="") as handle:
            enriched = list(csv.DictReader(handle))
        assert enriched[0]["bit_index"] == "31"
        assert enriched[0]["center_of_mass_velocity_error"] == "0.5"
        serialized = json.loads(enriched[0]["corr_vec"])
        assert serialized[:6] == [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
        assert np.isnan(serialized[6])

        phase_rows = directory / "phase.csv"
        phase_rows.write_text(
            "source_id,strict_phase_supported,nominal_strict_phase_mass3\n"
            f"{source_a},True,True\n"
            f"{source_b},False,False\n",
            encoding="utf-8",
        )
        phase_summary = directory / "summary.json"
        phase_summary.write_text(
            json.dumps({"candidate_safe": True}),
            encoding="utf-8",
        )
        reference = SimpleNamespace(
            maximum_absolute_difference=0.0,
            reference_api="nsstools.NssSource.covmat",
        )
        with patch(
            "gaia_covariance_vetting.compare_with_nsstools",
            return_value=reference,
        ):
            result = augment_covariance_phase_products(
                candidate_gaia=candidate_gaia,
                phase_rows=phase_rows,
                phase_summary=phase_summary,
                draws=10_000,
                global_seed=42,
            )

        assert result["candidate_safe"] is True
        assert result["candidate_sources"] == 2
        assert result["sources_dpac_covariance_parity_within_tolerance"] == 2
        assert (
            result[
                "sources_both_strict_phase_and_covariance_q15_865_"
                "minimum_mass_at_least_3_solar"
            ]
            == 1
        )
        assert result["nominal_promoted_sources_surviving_covariance_q0_135_mass"] == 1
        stored = json.loads(phase_summary.read_text(encoding="utf-8"))
        assert stored["gaia_covariance_vetting"] == result
        with phase_rows.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["covariance_q15_865_strict_phase_mass3"] == "True"
        assert float(rows[0]["minimum_companion_mass_covariance_q15_865_solar"]) > 3
        assert float(rows[1]["minimum_companion_mass_covariance_median_solar"]) < 3
