from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_lamost_obsid_csv_v2.py"
SPEC = importlib.util.spec_from_file_location("probe_lamost_obsid_csv_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LamostObsidCsvV2Tests(unittest.TestCase):
    def test_combined_prefix_is_removed(self) -> None:
        parsed = MODULE._parse_delimited_compat(
            b"combined_obsid|combined_rv|combined_rv_err|combined_fibermask\n"
            b"123|10.5|1.2|0\n"
        )
        self.assertIsNotNone(parsed)
        delimiter, columns, row_count, rows = parsed
        self.assertEqual(delimiter, "|")
        self.assertEqual(columns, ["obsid", "rv", "rv_err", "fibermask"])
        self.assertEqual(row_count, 1)
        self.assertEqual(rows[0][0], "123")

    def test_mixed_headers_are_preserved_or_normalized(self) -> None:
        normalized = MODULE._normalize_parsed(
            (",", ["combined_obsid", "rv", "combined_rv_err", "fibermask"], 0, [])
        )
        self.assertEqual(normalized[1], ["obsid", "rv", "rv_err", "fibermask"])

    def test_collision_after_normalization_fails_closed(self) -> None:
        with self.assertRaisesRegex(Exception, "duplicate headers"):
            MODULE._normalize_parsed(
                (",", ["obsid", "combined_obsid"], 0, [])
            )


if __name__ == "__main__":
    unittest.main()
