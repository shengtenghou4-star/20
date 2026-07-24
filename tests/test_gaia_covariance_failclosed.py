from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

CAPSULE = Path(__file__).resolve().parents[1] / "capsules" / "hou_compact_final" / "hou_compact"
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(CAPSULE))

from gaia_covariance_failclosed import augment_covariance_phase_products  # noqa: E402


def test_production_python_startup_installs_failclosed_hook(tmp_path: Path) -> None:
    script = tmp_path / "phase_followup_pipeline.py"
    script.write_text(
        "import sitecustomize\n"
        "hook = sitecustomize._AUGMENT_COVARIANCE_PHASE_PRODUCTS\n"
        "print(hook.__module__)\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(CAPSULE), str(SRC)))
    completed = subprocess.run(
        [sys.executable, str(script), "validate"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.stdout.strip() == "gaia_covariance_failclosed"


def test_missing_flame_lower_fails_closed_without_blocking_evaluable_source(
    tmp_path: Path,
) -> None:
    source_valid = "1234567890123456789"
    source_missing = "3234567890123456789"
    corr_vec = json.dumps(
        [0.0] * 6 + [float("nan")] * 225,
        allow_nan=True,
        separators=(",", ":"),
    )
    candidate_gaia = tmp_path / "candidate_gaia.csv"
    fields = [
        "source_id",
        "nss_solution_type",
        "period",
        "period_error",
        "center_of_mass_velocity",
        "center_of_mass_velocity_error",
        "semi_amplitude_primary",
        "semi_amplitude_primary_error",
        "t_periastron",
        "t_periastron_error",
        "eccentricity",
        "eccentricity_error",
        "arg_periastron",
        "arg_periastron_error",
        "bit_index",
        "corr_vec",
        "mass_flame_lower",
    ]
    with candidate_gaia.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "source_id": source_valid,
                    "nss_solution_type": "SB1C",
                    "period": "10",
                    "period_error": "0.1",
                    "center_of_mass_velocity": "5",
                    "center_of_mass_velocity_error": "0.5",
                    "semi_amplitude_primary": "150",
                    "semi_amplitude_primary_error": "1",
                    "t_periastron": "100",
                    "t_periastron_error": "0.2",
                    "eccentricity": "0",
                    "eccentricity_error": "0",
                    "arg_periastron": "0",
                    "arg_periastron_error": "0",
                    "bit_index": "31",
                    "corr_vec": corr_vec,
                    "mass_flame_lower": "1.0",
                },
                {
                    "source_id": source_missing,
                    "nss_solution_type": "SB1C",
                    "period": "20",
                    "period_error": "0.2",
                    "center_of_mass_velocity": "-10",
                    "center_of_mass_velocity_error": "1",
                    "semi_amplitude_primary": "30",
                    "semi_amplitude_primary_error": "2",
                    "t_periastron": "200",
                    "t_periastron_error": "0.3",
                    "eccentricity": "0",
                    "eccentricity_error": "0",
                    "arg_periastron": "0",
                    "arg_periastron_error": "0",
                    "bit_index": "31",
                    "corr_vec": corr_vec,
                    "mass_flame_lower": "",
                },
            ]
        )

    phase_rows = tmp_path / "phase.csv"
    phase_rows.write_text(
        "source_id,strict_phase_supported,nominal_strict_phase_mass3\n"
        f"{source_valid},True,True\n"
        f"{source_missing},False,False\n",
        encoding="utf-8",
    )
    phase_summary = tmp_path / "summary.json"
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

    assert result["candidate_sources"] == 2
    assert result["sources_covariance_mass_evaluable"] == 1
    assert result["sources_covariance_mass_not_evaluable"] == 1
    assert result["sources_missing_positive_flame_lower_mass"] == 1
    assert result["sources_dpac_covariance_parity_within_tolerance"] == 2
    assert (
        result[
            "sources_both_strict_phase_and_covariance_q15_865_"
            "minimum_mass_at_least_3_solar"
        ]
        == 1
    )

    with phase_rows.open("r", encoding="utf-8", newline="") as handle:
        rows = {row["source_id"]: row for row in csv.DictReader(handle)}
    assert rows[source_valid]["gaia_covariance_mass_evaluable"] == "True"
    assert rows[source_valid]["covariance_q15_865_strict_phase_mass3"] == "True"
    assert rows[source_missing]["gaia_covariance_mass_evaluable"] == "False"
    assert (
        rows[source_missing]["gaia_covariance_mass_non_evaluable_reason"]
        == "missing_mass_flame_lower"
    )
    assert rows[source_missing]["covariance_q15_865_strict_phase_mass3"] == "False"
    assert rows[source_missing]["covariance_q2_275_strict_phase_mass3"] == "False"
    assert rows[source_missing]["covariance_q0_135_strict_phase_mass3"] == "False"
