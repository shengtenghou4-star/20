from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from astropy.io import fits

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "probe_lamost_spectrum_time_header.py"
)
SPEC = importlib.util.spec_from_file_location(
    "probe_lamost_spectrum_time_header",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SpectrumTimeHeaderProbeTests(unittest.TestCase):
    def make_fits(self, *, obsid: str, date_obs: str) -> bytes:
        header = fits.Header()
        header["OBSID"] = int(obsid)
        header["DATE-OBS"] = date_obs
        header["DATE-BEG"] = "2018-02-20T20:30:18.0"
        header["DATE-END"] = "2018-02-20T21:06:58.0"
        header["MJD"] = 58169
        header["LMJD"] = 58170
        header["LMJMLIST"] = "83764590-83764603-83764616"
        header["EXPTIME"] = 1800.0
        header["BESTEXP"] = 83764590
        stream = io.BytesIO()
        fits.PrimaryHDU(data=None, header=header).writeto(stream)
        return stream.getvalue()

    def test_scalar_shape_never_returns_original_value(self) -> None:
        value = "2018-02-20T12:48:00"
        shape = MODULE._scalar_shape(value)
        self.assertTrue(shape["iso_datetime"])
        self.assertEqual(shape["length"], len(value))
        self.assertNotIn(value, json.dumps(shape))

    def test_json_contract_keeps_safe_keys_and_redacts_values(self) -> None:
        obsid = "648816210"
        raw = json.dumps(
            {
                "status": "ok",
                "data": {
                    "obsid": obsid,
                    "date_obs": "2018-02-20T12:48:00",
                    "mjd": "58169.53333",
                },
                obsid: "unsafe-key-value",
            }
        ).encode("utf-8")
        contract = MODULE._inspect_json(raw, expected_obsid=obsid)
        rendered = json.dumps(contract, sort_keys=True)
        self.assertIn("date_obs", contract["safe_key_names"])
        self.assertEqual(contract["unsafe_key_count"], 1)
        self.assertEqual(contract["obsid_exact_match_count"], 1)
        self.assertNotIn(obsid, rendered)
        self.assertNotIn("2018-02-20", rendered)
        self.assertTrue(
            any(
                item["path"].endswith(".date_obs")
                and item["shape"]["iso_datetime"]
                for item in contract["time_field_shapes"]
            )
        )

    def test_same_origin_followups_reject_cross_origin_urls(self) -> None:
        payload = {
            "safe": "https://www.lamost.org/download/example.fits",
            "relative": "/openapi/files/example.fits",
            "unsafe": "https://example.com/private.fits",
        }
        urls = MODULE._same_origin_followup_urls(
            payload,
            base_url="https://www.lamost.org/openapi/dr8/v1.0/lrs/spectrum/fits",
        )
        self.assertEqual(len(urls), 2)
        self.assertTrue(all("www.lamost.org" in url for url in urls))
        self.assertTrue(all("example.com" not in url for url in urls))

    def test_fits_header_exact_obsid_and_date_obs_pass(self) -> None:
        obsid = "648816210"
        raw = self.make_fits(obsid=obsid, date_obs="2018-02-20T12:48:00")
        contract = MODULE._inspect_fits_header(raw, expected_obsid=obsid)
        rendered = json.dumps(contract, sort_keys=True)
        self.assertTrue(contract["header_obsid_matches_requested"])
        self.assertTrue(contract["date_obs_is_iso_datetime"])
        self.assertTrue(contract["precise_observation_midpoint_available"])
        self.assertIn("DATE-OBS", contract["review_keywords_present"])
        self.assertNotIn(obsid, rendered)
        self.assertNotIn("2018-02-20", rendered)
        self.assertNotIn("OBSID", contract["time_keyword_shapes"])

    def test_wrong_fits_obsid_fails_identity_assessment(self) -> None:
        raw = self.make_fits(
            obsid="648816210",
            date_obs="2018-02-20T12:48:00",
        )
        contract = MODULE._inspect_fits_header(raw, expected_obsid="648816211")
        self.assertFalse(contract["header_obsid_matches_requested"])
        self.assertFalse(contract["precise_observation_midpoint_available"])

    def test_date_only_is_not_precise_observation_midpoint(self) -> None:
        obsid = "648816210"
        raw = self.make_fits(obsid=obsid, date_obs="2018-02-20")
        contract = MODULE._inspect_fits_header(raw, expected_obsid=obsid)
        self.assertFalse(contract["date_obs_is_iso_datetime"])
        self.assertFalse(contract["precise_observation_midpoint_available"])

    def test_safe_failure_output_omits_exception_details_for_unknown_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "failure.json"
            result = MODULE._write_failure(output, RuntimeError("648816210 secret"))
            rendered = output.read_text(encoding="utf-8")
            self.assertEqual(result["error_code"], "unexpected_error")
            self.assertNotIn("648816210", rendered)
            self.assertNotIn("secret", rendered)


if __name__ == "__main__":
    unittest.main()
