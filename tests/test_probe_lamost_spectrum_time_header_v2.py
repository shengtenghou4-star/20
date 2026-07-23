from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

from astropy.io import fits

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SCRIPT = SCRIPTS / "probe_lamost_spectrum_time_header_v2.py"
SPEC = importlib.util.spec_from_file_location(
    "probe_lamost_spectrum_time_header_v2",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_fits() -> bytes:
    header = fits.Header()
    header["OBSID"] = 648816210
    header["DATE-OBS"] = "2018-02-20T12:48:00"
    stream = io.BytesIO()
    fits.PrimaryHDU(data=None, header=header).writeto(stream)
    return stream.getvalue()


class SpectrumTimeHeaderV2Tests(unittest.TestCase):
    def test_raw_fits_is_accepted_without_transformation(self) -> None:
        raw = make_fits()
        decoded, contract = MODULE._decode_fits_payload(raw)
        self.assertEqual(decoded, raw)
        self.assertEqual(contract["encoding"], "identity")
        self.assertTrue(contract["decoded_fits_magic"])

    def test_gzip_fits_is_crc_verified_and_decoded(self) -> None:
        raw = make_fits()
        compressed = gzip.compress(raw, mtime=0)
        decoded, contract = MODULE._decode_fits_payload(compressed)
        self.assertEqual(decoded, raw)
        self.assertEqual(contract["encoding"], "gzip")
        self.assertTrue(contract["gzip_crc_read_to_eof"])
        self.assertTrue(contract["decoded_fits_magic"])
        rendered = json.dumps(contract, sort_keys=True)
        self.assertNotIn("648816210", rendered)
        self.assertNotIn("2018-02-20", rendered)

    def test_truncated_gzip_fails_closed(self) -> None:
        compressed = gzip.compress(make_fits(), mtime=0)
        with self.assertRaisesRegex(
            MODULE.base.SpectrumTimeContractError,
            "integrity check failed",
        ):
            MODULE._decode_fits_payload(compressed[:-8])

    def test_non_fits_payload_records_magic_only(self) -> None:
        decoded, contract = MODULE._decode_fits_payload(b'{"detail":"not a fits"}')
        self.assertIsNone(decoded)
        self.assertEqual(contract["encoding"], "unknown")
        self.assertFalse(contract["decoded_fits_magic"])
        self.assertNotIn("detail", json.dumps(contract))

    def test_gzip_non_fits_remains_rejected(self) -> None:
        compressed = gzip.compress(b"not a fits", mtime=0)
        decoded, contract = MODULE._decode_fits_payload(compressed)
        self.assertIsNone(decoded)
        self.assertEqual(contract["encoding"], "gzip")
        self.assertFalse(contract["decoded_fits_magic"])


if __name__ == "__main__":
    unittest.main()
