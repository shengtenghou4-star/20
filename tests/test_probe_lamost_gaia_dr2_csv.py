from __future__ import annotations

import importlib.util
import io
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_lamost_gaia_dr2_csv.py"
SPEC = importlib.util.spec_from_file_location("probe_lamost_gaia_dr2_csv", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeOpener:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, _request, timeout: float):
        self.assert_timeout = timeout
        return FakeResponse(self.payload)


class GaiaDr2FormProbeTests(unittest.TestCase):
    def test_official_sample_selection_is_redacted_to_hash(self) -> None:
        value = "2676113965163724160"
        selected, receipt = MODULE._fetch_sample(
            FakeOpener((value + "\n").encode("ascii")),
            "https://www.lamost.org/dr8/v1.0/u/gaia_source_id.txt",
            30.0,
        )
        self.assertEqual(selected, value)
        self.assertNotIn(value, str(receipt))
        self.assertEqual(len(receipt["selected_id_sha256"]), 64)

    def test_non_exact_sample_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.GaiaFormProbeError, "no exact Gaia"):
            MODULE._fetch_sample(
                FakeOpener(b"2.676e18\n"),
                "https://www.lamost.org/dr8/v1.0/u/gaia_source_id.txt",
                30.0,
            )

    def test_required_contract_includes_rv_quality_and_identity(self) -> None:
        self.assertEqual(
            MODULE._REQUIRED,
            {"gaia_source_id", "obsid", "rv", "rv_err", "fibermask"},
        )
        self.assertIn("gaia_source_id", MODULE._OUTPUT)
        self.assertIn("obsid", MODULE._OUTPUT)


if __name__ == "__main__":
    unittest.main()
