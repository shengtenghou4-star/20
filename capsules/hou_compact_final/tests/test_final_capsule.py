from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

from astropy.io import fits
from astropy.table import Table
from astropy.time import Time

CAPSULE = Path(__file__).resolve().parents[1] / "hou_compact"
sys.path.insert(0, str(CAPSULE))

from gaia_candidate_vetting import augment_candidate_gaia, augment_phase_products  # noqa: E402
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

    def test_fits_date_obs_is_authoritative_when_mec_disagrees(self) -> None:
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
                        "mid_mjd": fits_mjd_1 + 750.0 / 86400.0,
                        "time_quantisation_half_width_days": 30.0 / 86400.0,
                    }
                )
                writer.writerow(
                    {
                        "obsid": "1002",
                        "hou_compact_dr3_source_id": "1234567890123456789",
                        "mid_mjd": fits_mjd_2 + 30.0 / 86400.0,
                        "time_quantisation_half_width_days": 30.0 / 86400.0,
                    }
                )
            output = directory / "hybrid.csv"
            safe = build_hybrid(
                expected_path=expected,
                mec_path=mec,
                fits_manifest=manifest,
                output_path=output,
                private_receipt_path=directory / "private.json",
                safe_summary_path=directory / "safe.json",
            )
            self.assertEqual(
                safe["mec_fits_mismatches_against_public_31_second_contract"],
                1,
            )
            self.assertEqual(safe["final_obsids"], 2)
            self.assertAlmostEqual(safe["maximum_crosscheck_residual_seconds"], 750.0, places=3)
            with output.open("r", encoding="utf-8", newline="") as handle:
                stored_rows = list(csv.DictReader(handle))
            self.assertEqual(
                {row["time_source"] for row in stored_rows},
                {"fits_date_obs_authoritative"},
            )
            self.assertAlmostEqual(float(stored_rows[0]["mid_mjd"]), fits_mjd_1, places=10)
            self.assertAlmostEqual(float(stored_rows[1]["mid_mjd"]), fits_mjd_2, places=10)
            stored = json.loads((directory / "safe.json").read_text())
            self.assertEqual(stored["final_sources"], 1)
            self.assertEqual(stored["authoritative_fits_obsids"], 2)

    def test_one_sigma_mass_geometry_and_duplicate_vetting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source_a = "1234567890123456789"
            source_b = "3234567890123456789"
            gaia_ecsv = directory / "gaia.ecsv"
            Table(
                {
                    "source_id": [int(source_a), int(source_b)],
                    "nss_solution_type": ["SB1C", "SB1C"],
                    "period": [10.0, 20.0],
                    "period_error": [0.1, 0.2],
                    "gaia_ref_epoch": [2016.0, 2016.0],
                    "t_periastron": [0.0, 0.0],
                    "eccentricity": [0.0, 0.0],
                    "eccentricity_error": [0.0, 0.0],
                    "arg_periastron": [0.0, 0.0],
                    "semi_amplitude_primary": [150.0, 30.0],
                    "semi_amplitude_primary_error": [1.0, 2.0],
                    "mass_flame": [1.1, 1.0],
                    "mass_flame_lower": [1.0, 0.9],
                    "mass_flame_upper": [1.2, 1.1],
                    "flags_flame": ["0", "0"],
                    "radius_gspphot": [1.0, 1.0],
                    "radius_gspphot_lower": [0.9, 0.9],
                    "radius_gspphot_upper": [1.1, 1.1],
                    "duplicated_source": [False, True],
                    "ipd_frac_multi_peak": [0.0, 2.0],
                    "ipd_frac_odd_win": [0.0, 1.0],
                    "phot_bp_n_obs": [20, 20],
                    "phot_rp_n_obs": [20, 20],
                    "phot_bp_n_contaminated_transits": [0, 1],
                    "phot_bp_n_blended_transits": [0, 1],
                    "phot_rp_n_contaminated_transits": [0, 1],
                    "phot_rp_n_blended_transits": [0, 1],
                    "phot_bp_rp_excess_factor": [1.1, 1.2],
                    "ruwe": [1.0, 1.5],
                    "astrometric_gof_al": [0.0, 2.0],
                    "astrometric_excess_noise": [0.0, 1.0],
                    "astrometric_excess_noise_sig": [0.0, 5.0],
                    "rv_n_good_obs_primary": [20, 10],
                    "conf_spectro_period": [0.99, 0.9],
                    "goodness_of_fit": [1.0, 2.0],
                    "efficiency": [0.9, 0.7],
                    "significance": [20.0, 10.0],
                    "flags": [0, 0],
                }
            ).write(gaia_ecsv, format="ascii.ecsv", overwrite=True)
            candidate_gaia = directory / "candidate_gaia.csv"
            candidate_gaia.write_text(
                "source_id,nss_solution_type,period,gaia_ref_epoch,t_periastron,eccentricity,arg_periastron,semi_amplitude_primary,mass_flame,mass_flame_lower,mass_flame_upper,flags_flame\n"
                f"{source_a},SB1C,10,2016,0,0,0,150,1.1,1.0,1.2,0\n"
                f"{source_b},SB1C,20,2016,0,0,0,30,1.0,0.9,1.1,0\n",
                encoding="utf-8",
            )
            appended = augment_candidate_gaia(
                gaia_ecsv=gaia_ecsv,
                candidate_gaia=candidate_gaia,
            )
            self.assertEqual(appended["candidate_sources"], 2)
            with candidate_gaia.open("r", encoding="utf-8", newline="") as handle:
                enriched = list(csv.DictReader(handle))
            self.assertEqual(enriched[0]["period_error"], "0.1")
            self.assertEqual(enriched[1]["duplicated_source"], "True")

            phase_rows = directory / "phase.csv"
            phase_rows.write_text(
                "source_id,strict_phase_supported,minimum_companion_mass_using_primary_lower_solar\n"
                f"{source_a},True,5.0\n"
                f"{source_b},False,1.0\n",
                encoding="utf-8",
            )
            phase_summary = directory / "summary.json"
            phase_summary.write_text(
                json.dumps({"candidate_safe": True, "contract": {}}),
                encoding="utf-8",
            )
            vetting = augment_phase_products(
                candidate_gaia=candidate_gaia,
                phase_rows=phase_rows,
                phase_summary=phase_summary,
            )
            self.assertEqual(
                vetting["sources_both_strict_phase_and_1sigma_minimum_mass_at_least_3_solar"],
                1,
            )
            self.assertEqual(vetting["basic_mass_geometry_duplicate_vetting_survivors"], 1)
            self.assertEqual(vetting["sources_duplicated_source_true"], 1)
            stored_summary = json.loads(phase_summary.read_text(encoding="utf-8"))
            self.assertIn("gaia_stellar_orbit_vetting", stored_summary)
            with phase_rows.open("r", encoding="utf-8", newline="") as handle:
                scored = list(csv.DictReader(handle))
            self.assertEqual(scored[0]["robust_1sigma_strict_phase_mass3"], "True")
            self.assertEqual(scored[0]["stressed_roche_fill_below_0_8"], "True")


if __name__ == "__main__":
    unittest.main()
