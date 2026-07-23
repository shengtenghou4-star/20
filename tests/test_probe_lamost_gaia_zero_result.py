from __future__ import annotations

import hashlib
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_lamost_gaia_zero_result.py"
SPEC = importlib.util.spec_from_file_location("probe_lamost_gaia_zero_result", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GaiaZeroResultContractTests(unittest.TestCase):
    def test_fixed_probe_is_exact_and_only_hash_is_expected_in_receipt(self) -> None:
        self.assertRegex(MODULE._PROBE_ID, r"^[0-9]{10,20}$")
        digest = hashlib.sha256(MODULE._PROBE_ID.encode("ascii")).hexdigest()
        self.assertEqual(len(digest), 64)
        self.assertNotEqual(digest, MODULE._PROBE_ID)

    def test_required_outputs_cover_identity_rv_error_and_quality(self) -> None:
        self.assertEqual(
            set(MODULE._OUTPUT),
            {"gaia_source_id", "obsid", "lmjd", "rv", "rv_err", "fibermask"},
        )

    def test_markers_are_generic_and_contain_no_identifier(self) -> None:
        joined = " ".join(MODULE._MARKERS)
        self.assertNotIn(MODULE._PROBE_ID, joined)
        self.assertIn("no result", MODULE._MARKERS)
        self.assertIn("error", MODULE._MARKERS)
        self.assertIn("limit", MODULE._MARKERS)


if __name__ == "__main__":
    unittest.main()
