from __future__ import annotations

import io
import unittest
from urllib.request import Request

from hou_compact import lamost_gaia_form_rv as base
from hou_compact.lamost_gaia_form_rv_v3 import (
    _ZERO_RESULT_COLUMNS,
    _fetch_batch_zero_aware,
)


class FakeResponse(io.BytesIO):
    def __init__(
        self,
        payload: bytes,
        *,
        url: str,
        content_type: str = "",
        disposition: str = "",
    ) -> None:
        super().__init__(payload)
        self.status = 200
        self.headers = {
            "Content-Type": content_type,
            "Content-Disposition": disposition,
        }
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def geturl(self) -> str:
        return self._url


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float):
        if timeout <= 0:
            raise AssertionError("timeout must be positive")
        self.requests.append(request)
        return self.response


class GaiaFormEmptyBatchTests(unittest.TestCase):
    ACTION = "https://www.lamost.org/dr8/v1.0/q"
    REFERER = "https://www.lamost.org/dr8/v1.0/search"
    IDS = ("2234567890123456789",)
    OUTPUTS = (
        "gaia_source_id",
        "obsid",
        "lmjd",
        "mjd",
        "obsdate",
        "rv",
        "rv_err",
        "snrg",
        "snri",
        "class",
        "subclass",
        "fibermask",
    )

    def fetch(self, response: FakeResponse):
        return _fetch_batch_zero_aware(
            FakeOpener(response),
            action_url=self.ACTION,
            referer_url=self.REFERER,
            dr2_ids=self.IDS,
            output_columns=self.OUTPUTS,
            collection="minimal",
            timeout=30.0,
            maximum_response_bytes=1024 * 1024,
        )

    def test_verified_empty_attachment_becomes_zero_row_frozen_table(self) -> None:
        table, receipts = self.fetch(
            FakeResponse(
                b"",
                url=self.ACTION,
                disposition='attachment; filename="0.csv"',
            )
        )
        self.assertEqual(table.columns, _ZERO_RESULT_COLUMNS)
        self.assertEqual(table.rows, ())
        self.assertEqual(table.response_bytes, 0)
        self.assertEqual(table.source_kind, "form_post_empty_attachment")
        self.assertTrue(receipts[0]["verified_zero_result_attachment"])
        records, columns = base._validate_batch(
            table,
            requested_ids=set(self.IDS),
            expected_columns=_ZERO_RESULT_COLUMNS,
        )
        self.assertEqual(records, [])
        self.assertEqual(columns, _ZERO_RESULT_COLUMNS)

    def test_empty_response_without_attachment_is_fatal(self) -> None:
        with self.assertRaisesRegex(base.LamostGaiaFormError, "without the verified"):
            self.fetch(FakeResponse(b"", url=self.ACTION))

    def test_empty_attachment_from_different_path_is_fatal(self) -> None:
        with self.assertRaisesRegex(base.LamostGaiaFormError, "without the verified"):
            self.fetch(
                FakeResponse(
                    b"",
                    url="https://www.lamost.org/dr8/v1.0/error",
                    disposition='attachment; filename="0.csv"',
                )
            )

    def test_nonempty_combined_response_is_still_strictly_parsed(self) -> None:
        payload = (
            "combined_obsid|combined_obsdate|combined_lmjd|combined_mjd|"
            "combined_snrg|combined_snri|combined_class|combined_subclass|"
            "combined_ra|combined_dec|combined_fibermask|combined_gaia_source_id|"
            "combined_rv_err|combined_rv\n"
            "1001|2020-01-01|59000|59000|20|18|STAR|G2|1|2|0|"
            "2234567890123456789|1.2|30.0\n"
        ).encode("utf-8")
        table, receipts = self.fetch(
            FakeResponse(
                payload,
                url=self.ACTION,
                disposition='attachment; filename="1.csv"',
            )
        )
        self.assertEqual(table.columns, _ZERO_RESULT_COLUMNS)
        self.assertEqual(len(table.rows), 1)
        self.assertFalse(receipts[0]["verified_zero_result_attachment"])


if __name__ == "__main__":
    unittest.main()
