from __future__ import annotations

import csv
import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compute_sb1_mass_function.py"
SPEC = importlib.util.spec_from_file_location("compute_sb1_mass_function", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SB1MassFunctionTests(unittest.TestCase):
    def test_known_one_day_hundred_kms_mass_function(self) -> None:
        result = MODULE.mass_function_solar(1.0, 100.0, 0.0)
        self.assertAlmostEqual(result, 0.10361177345, places=10)

    def test_minimum_companion_mass_satisfies_mass_function(self) -> None:
        mass_function = 0.5
        primary_mass = 1.0
        companion = MODULE.minimum_companion_mass_solar(mass_function, primary_mass)
        reconstructed = companion**3 / (primary_mass + companion) ** 2
        self.assertTrue(math.isclose(reconstructed, mass_function, rel_tol=1e-12))

    def test_sb1c_missing_eccentricity_is_treated_as_circular(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            input_path = directory / "input.ecsv"
            output_path = directory / "output.csv"
            summary_path = directory / "summary.json"
            input_path.write_text(
                "# %ECSV 1.0\n"
                "source_id,nss_solution_type,period,semi_amplitude_primary,eccentricity,mass_flame_lower,binary_mass_m1_lower,binary_mass_m1,binary_mass_m2_lower\n"
                "1234567890123456789,SB1C,10,120,,1.0,,,,\n",
                encoding="utf-8",
            )
            summary = MODULE.compute_table(input_path, output_path, summary_path)
            self.assertEqual(summary["accepted_sources"], 1)
            with output_path.open("r", encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["eccentricity"], "0")
            self.assertTrue(float(row["mass_function_solar"]) > 1.0)
            self.assertIn("minimum_mass_ge_", row["mass_tier"])

    def test_sb1_missing_eccentricity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            input_path = directory / "input.csv"
            input_path.write_text(
                "source_id,nss_solution_type,period,semi_amplitude_primary,eccentricity,mass_flame_lower\n"
                "1234567890123456789,SB1,10,50,,1.0\n",
                encoding="utf-8",
            )
            summary = MODULE.compute_table(
                input_path,
                directory / "output.csv",
                directory / "summary.json",
            )
            self.assertEqual(summary["accepted_sources"], 0)
            self.assertEqual(summary["rejected_rows"], 1)


if __name__ == "__main__":
    unittest.main()
