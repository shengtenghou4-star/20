from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_lamost_obsid_csv.py"
SPEC = importlib.util.spec_from_file_location("probe_lamost_obsid_csv", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LamostObsidCsvProbeTests(unittest.TestCase):
    def test_multipart_body_contains_fields_but_no_filename(self) -> None:
        body = MODULE._multipart_body(
            [("sForm", "0"), ("obsidTextarea", "123456789")],
            "BOUNDARY",
        )
        text = body.decode("utf-8")
        self.assertIn('name="sForm"', text)
        self.assertIn('name="obsidTextarea"', text)
        self.assertIn("123456789", text)
        self.assertNotIn("filename=", text)
        self.assertTrue(text.endswith("--BOUNDARY--\r\n"))

    def test_csv_parser_selects_comma_delimiter(self) -> None:
        parsed = MODULE._parse_delimited(
            b"obsid,rv,rv_err,fibermask\n123,10.5,1.2,0\n"
        )
        self.assertIsNotNone(parsed)
        delimiter, columns, row_count, rows = parsed
        self.assertEqual(delimiter, ",")
        self.assertEqual(columns, ["obsid", "rv", "rv_err", "fibermask"])
        self.assertEqual(row_count, 1)
        self.assertEqual(rows[0][0], "123")

    def test_pipe_parser_and_malformed_width(self) -> None:
        parsed = MODULE._parse_delimited(
            b"obsid|rv|rv_err|fibermask\n123|10|1|0\n"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], "|")
        self.assertIsNone(MODULE._parse_delimited(b"a,b\n1,2,3\n"))

    def test_safe_url_metadata_strips_query_and_fragment(self) -> None:
        result = MODULE._safe_url_metadata(
            "https://www.lamost.org/dr8/v1.0/q?secret=123#fragment"
        )
        self.assertEqual(
            result["origin_and_path"],
            "https://www.lamost.org/dr8/v1.0/q",
        )
        self.assertEqual(len(result["full_url_sha256"]), 64)
        self.assertNotIn("secret", str(result))

    def test_followup_candidates_are_same_origin_and_rank_csv(self) -> None:
        html = b"""
        <a href="https://evil.example/result.csv">bad</a>
        <a href="/dr8/v1.0/download/result.csv?token=abc">csv</a>
        <a href="/dr8/v1.0/result/42">result</a>
        """
        links = MODULE._same_origin_candidates(
            html,
            "https://www.lamost.org/dr8/v1.0/q",
        )
        self.assertEqual(
            links[0],
            "https://www.lamost.org/dr8/v1.0/download/result.csv?token=abc",
        )
        self.assertTrue(all("evil.example" not in value for value in links))


if __name__ == "__main__":
    unittest.main()
