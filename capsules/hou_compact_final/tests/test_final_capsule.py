from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from astropy.io import fits
from astropy.time import Time

CAPSULE = Path(__file__).resolve().parents[1] / "hou_compact"
sys.path.insert(0, str(CAPSULE))

from gaia_rv_phase_validation import GaiaOrbit, julian_year_to_mjd  # noqa: E402
from gaia_rv_phase_validation_timed import TimedRVPoint, validate_timed_phase  # noqa: E402
from lamost_hybrid_time import build as build_hybrid  # noqa: E402
from lamost_mec_utc_time import lmjm_to_utc_mjd, quantisation_days  # noqa: E402
from phase_followup_pipeline import mass_function_solar, minimum_companion_mass  # noqa: E402


class FinalCapsuleTests(unittest.TestCase):
    def test_lmjm_utc_plus_8_conversion_and_quantisation(self) -> None:
        self.assertEqual(lmjm_to_utc_mjd("83764590"), "58169.520833333333")
        self.assertEqual(lmjm_to_utc_mjd("83764590.5"), "58169.521180555556")
        self.assertEqual(
            quantisation_days("83764590"),
            "0.0003472222222222222222222222222",
        )

    def test_synthetic_gaia_phase_support_requires_true_direction(self) -> None:
        orbit = GaiaOrbit(
            source_id="1234567890123456789",
            solution_type="SB1C",
            period_days=10.0,
            ref_epoch_jyear=2016.0,
            t_periastron_days=0.0,
            eccentricity=0.0,
            arg_periastron_deg=0.0,
            semi_amplitude_kms=30.0,
        )
        reference = julian_year_to_mjd(2016.0)
        points = [
            TimedRVPoint("1001", orbit.source_id, reference, 1e-6, 37.0, 1.0),
            TimedRVPoint("1002", orbit.source_id, reference + 2.5, 1e-6, 7.0, 1.0),
            TimedRVPoint("1003", orbit.source_id, reference + 5.0, 1e-6, -23.0, 1.0),
        ]
        result = validate_timed_phase(orbit, points)
        self.assertTrue(result["strict_phase_supported"])
        constant = [
            TimedRVPoint("2001", orbit.source_id, reference, 1e-6, 10.0, 1.0),
            TimedRVPoint("2002", orbit.source_id, reference + 2.5, 1e-6, 10.0, 1.0),
            TimedRVPoint("2003", orbit.source_id, reference + 5.0, 1e-6, 10.0, 1.0),
        ]
        rejected = validate_timed_phase(orbit, constant)
        self.assertFalse(rejected["strict_phase_supported"])
        self.assertGreater(rejected["zero_observed_informative_pairs"], 0)

    def test_mass_function_and_minimum_mass_are_monotonic(self) -> None:
        f_mass = mass_function_solar(10.0, 100.0, 0.0)
        self.assertGreater(f_mass, 1.0)
        low_primary = minimum_companion_mass(f_mass, 0.8)
        high_primary = minimum_companion_mass(f_mass, 1.2)
        self.assertGreater(high_primary, low_primary)
        self.assertAlmostEqual(
            low_primary**3 / (0.8 + low_primary) ** 2,
            f_mass,
            places=10,
        )

    def test_hybrid_bridge_accepts_utc_corrected_mec_with_30_second_residual(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            expected = directory / "expected.csv"
            expected.write_text(
                "obsid,hou_compact_dr2_source_id,hou_compact_dr3_source_id\n"
                "1001,2234567890123456789,1234567890123456789\n"
                "1002,2234567890123456789,1234567890123456789\n",
                encoding="utf-8",
            )
            fits_dir = directory / "fits"
            fits_dir.mkdir()
            manifest = directory / "manifest.csv"
            rows = []
            for index, (obsid, token) in enumerate(
                [("1001", "2018-02-20T12:30:00"), ("1002", "2018-02-20T13:00:00")],
                start=1,
            ):
                header = fits.Header()
                header["SIMPLE"] = True
                header["BITPIX"] = 8
                header["NAXIS"] = 0
                header["OBSID"] = obsid
                header["DATE-OBS"] = token
                path = fits_dir / f"s{index}.fits"
                fits.PrimaryHDU(header=header).writeto(path)
                rows.append({"obsid": obsid, "fits_path": str(path)})
            with manifest.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["obsid", "fits_path"])
                writer.writeheader()
                writer.writerows(rows)
            fits_mjd_1 = float(Time("2018-02-20T12:30:00", format="isot", scale="utc").mjd)
            fits_mjd_2 = float(Time("2018-02-20T13:00:00", format="isot", scale="utc").mjd)
            mec = directory / "mec.csv"
            with mec.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "obsid",
                        "hou_compact_dr3_source_id",
                        "mid_mjd",
                        "time_quantisation_half_width_days",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "obsid": "1001",
                        "hou_compact_dr3_source_id": "1234567890123456789",
                        "mid_mjd": fits_mjd_1 + 30.0 / 86400.0,
                        "time_quantisation_half_width_days": 30.0 / 86400.0,
                    }
                )
                writer.writerow(
                    {
                        "obsid": "1002",
                        "hou_compact_dr3_source_id": "1234567890123456789",
                        "mid_mjd": fits_mjd_2,
                        "time_quantisation_half_width_days": 30.0 / 86400.0,
                    }
                )
            safe = build_hybrid(
                expected_path=expected,
                mec_path=mec,
                fits_manifest=manifest,
                output_path=directory / "hybrid.csv",
                private_receipt_path=directory / "private.json",
                safe_summary_path=directory / "safe.json",
            )
            self.assertEqual(safe["mec_fits_crosscheck_mismatches"], 0)
            self.assertEqual(safe["final_obsids"], 2)
            self.assertLessEqual(safe["maximum_crosscheck_residual_seconds"], 30.0001)
            stored = json.loads((directory / "safe.json").read_text())
            self.assertEqual(stored["final_sources"], 1)


if __name__ == "__main__":
    unittest.main()
