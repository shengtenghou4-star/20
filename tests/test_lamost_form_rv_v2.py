from __future__ import annotations

import unittest

from hou_compact import lamost_form_rv as base
from hou_compact.lamost_form_rv_v2 import (
    _parse_delimited_compat,
    normalize_parsed_table,
)


class LamostFormRVV2Tests(unittest.TestCase):
    def test_pipe_response_with_combined_headers_is_normalized(self) -> None:
        table = _parse_delimited_compat(
            b"combined_obsid|combined_rv|combined_rv_err|combined_fibermask\n"
            b"123|10.5|1.2|0\n",
            source_kind="form_post",
            source_url="https://www.lamost.org/dr8/v1.0/q",
        )
        self.assertIsNotNone(table)
        assert table is not None
        self.assertEqual(table.delimiter, "|")
        self.assertEqual(table.columns, ("obsid", "rv", "rv_err", "fibermask"))
        records, columns = base._validate_table(
            table,
            requested_obsids={"123"},
            expected_columns=None,
        )
        self.assertEqual(columns, table.columns)
        self.assertEqual(records[0]["obsid"], "123")

    def test_transport_metadata_is_preserved(self) -> None:
        original = base.ParsedTable(
            delimiter="|",
            columns=("combined_obsid", "combined_rv", "combined_rv_err", "combined_fibermask"),
            rows=(("123", "10", "1", "0"),),
            response_sha256="a" * 64,
            response_bytes=42,
            source_kind="form_post",
            source_url_path="https://www.lamost.org/dr8/v1.0/q",
        )
        normalized = normalize_parsed_table(original)
        assert normalized is not None
        self.assertEqual(normalized.response_sha256, original.response_sha256)
        self.assertEqual(normalized.response_bytes, 42)
        self.assertEqual(normalized.source_kind, "form_post")

    def test_collision_after_prefix_removal_fails_closed(self) -> None:
        original = base.ParsedTable(
            delimiter=",",
            columns=("obsid", "combined_obsid"),
            rows=(),
            response_sha256="b" * 64,
            response_bytes=0,
            source_kind="test",
            source_url_path="https://www.lamost.org/dr8/v1.0/q",
        )
        with self.assertRaisesRegex(base.LamostFormError, "duplicate headers"):
            normalize_parsed_table(original)


if __name__ == "__main__":
    unittest.main()
