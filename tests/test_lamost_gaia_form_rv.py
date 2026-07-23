from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request

from hou_compact.lamost_gaia_form_rv import (
    LamostGaiaFormError,
    acquire_gaia_form_rv,
    load_accepted_bridge,
)


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, *, url: str, content_type: str = "text/plain") -> None:
        super().__init__(payload)
        self.status = 200
        self.headers = {"Content-Type": content_type}
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def geturl(self) -> str:
        return self._url


@dataclass(frozen=True)
class ExpectedCall:
    method: str
    url: str
    response: FakeResponse


class FakeOpener:
    def __init__(self, calls: list[ExpectedCall]) -> None:
        self.calls = list(calls)
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float):
        if not self.calls:
            raise AssertionError("unexpected opener call")
        expected = self.calls.pop(0)
        self.requests.append(request)
        self.assertGreater(timeout, 0)
        if request.get_method() != expected.method:
            raise AssertionError(f"expected {expected.method}, got {request.get_method()}")
        if request.full_url != expected.url:
            raise AssertionError(f"expected {expected.url}, got {request.full_url}")
        return expected.response

    def assertGreater(self, first, second):
        if not first > second:
            raise AssertionError("timeout must be positive")


class LamostGaiaFormRVTests(unittest.TestCase):
    SEARCH = "https://www.lamost.org/dr8/v1.0/search"
    ACTION = "https://www.lamost.org/dr8/v1.0/q"
    HEADER = (
        "combined_obsid|combined_obsdate|combined_lmjd|combined_mjd|"
        "combined_snrg|combined_snri|combined_class|combined_subclass|"
        "combined_ra|combined_dec|combined_fibermask|combined_gaia_source_id|"
        "combined_rv_err|combined_rv\n"
    )

    def bridge(self, directory: Path, *, duplicate_dr2: bool = False) -> Path:
        rows = [
            "1234567890123456789,2234567890123456789,accepted_unique_or_separated_nearest",
            "3234567890123456789,4234567890123456789,accepted_unique_or_separated_nearest",
            "5234567890123456789,6234567890123456789,rejected_ambiguous_nearest",
        ]
        if duplicate_dr2:
            rows.append(
                "7234567890123456789,2234567890123456789,accepted_unique_or_separated_nearest"
            )
        path = directory / "bridge.csv"
        path.write_text(
            "source_id,dr2_source_id,dr2_bridge_status\n" + "\n".join(rows) + "\n",
            encoding="utf-8",
        )
        return path

    def search_call(self) -> ExpectedCall:
        return ExpectedCall(
            "GET",
            self.SEARCH,
            FakeResponse(b"<html></html>", url=self.SEARCH, content_type="text/html"),
        )

    def run_client(self, directory: Path, opener: FakeOpener, *, batch_size: int = 100):
        rows = directory / "rows.csv"
        overlap = directory / "overlap.csv"
        private = directory / "private.json"
        safe = directory / "safe.json"
        summary = acquire_gaia_form_rv(
            bridge_input=self.bridge(directory),
            rows_output=rows,
            overlap_output=overlap,
            private_manifest_path=private,
            safe_summary_path=safe,
            batch_size=batch_size,
            retries=1,
            opener=opener,
            sleep=lambda _seconds: None,
        )
        return summary, rows, overlap, private, safe

    def test_one_source_can_return_multiple_exact_spectra(self) -> None:
        payload = (
            self.HEADER
            + "1001|2020-01-01|59000|59000|20|18|STAR|G2|1|2|0|"
            "2234567890123456789|1.0|10.0\n"
            + "1002|2020-01-02|59001|59001|15|14|STAR|G2|1|2|0|"
            "2234567890123456789|1.2|30.0\n"
            + "2001|2020-01-03|59002|59002|12|11|STAR|K1|3|4|0|"
            "4234567890123456789|2.0|20.0\n"
        ).encode("utf-8")
        opener = FakeOpener(
            [
                self.search_call(),
                ExpectedCall(
                    "POST",
                    self.ACTION,
                    FakeResponse(payload, url=self.ACTION, content_type="text/plain"),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            summary, rows_path, overlap_path, private_path, safe_path = self.run_client(
                directory, opener
            )
            self.assertEqual(summary["returned_spectrum_rows"], 3)
            self.assertEqual(summary["returned_unique_dr2_sources"], 2)
            self.assertEqual(summary["bridge_sources_without_spectra"], 0)
            rows = list(csv.DictReader(rows_path.open(encoding="utf-8")))
            self.assertEqual([row["obsid"] for row in rows], ["1001", "1002", "2001"])
            self.assertEqual(
                rows[0]["hou_compact_dr3_source_id"], "1234567890123456789"
            )
            overlap = list(csv.DictReader(overlap_path.open(encoding="utf-8")))
            self.assertEqual(overlap[1]["lmjd"], "59001")
            safe_text = safe_path.read_text(encoding="utf-8")
            self.assertNotIn("2234567890123456789", safe_text)
            private = json.loads(private_path.read_text(encoding="utf-8"))
            self.assertEqual(private["batches"][0]["returned_spectrum_rows"], 3)
            self.assertFalse(opener.calls)

    def test_out_of_batch_gaia_id_fails_and_deletes_outputs(self) -> None:
        payload = (
            self.HEADER
            + "1001|2020-01-01|59000|59000|20|18|STAR|G2|1|2|0|"
            "9999999999999999999|1|10\n"
        ).encode("utf-8")
        opener = FakeOpener(
            [
                self.search_call(),
                ExpectedCall("POST", self.ACTION, FakeResponse(payload, url=self.ACTION)),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(LamostGaiaFormError, "outside the batch"):
                self.run_client(directory, opener)
            self.assertFalse((directory / "rows.csv").exists())
            self.assertFalse((directory / "overlap.csv").exists())
            self.assertNotIn(
                "9999999999999999999",
                (directory / "safe.json").read_text(encoding="utf-8"),
            )

    def test_duplicate_obsid_in_response_fails_closed(self) -> None:
        payload = (
            self.HEADER
            + "1001|2020-01-01|59000|59000|20|18|STAR|G2|1|2|0|"
            "2234567890123456789|1|10\n"
            + "1001|2020-01-02|59001|59001|20|18|STAR|G2|1|2|0|"
            "2234567890123456789|1|11\n"
        ).encode("utf-8")
        opener = FakeOpener(
            [
                self.search_call(),
                ExpectedCall("POST", self.ACTION, FakeResponse(payload, url=self.ACTION)),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(LamostGaiaFormError, "repeats an obsid"):
                self.run_client(Path(temporary), opener)

    def test_rejected_bridge_rows_are_not_queried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bridge = load_accepted_bridge(self.bridge(Path(temporary)))
            self.assertEqual(
                bridge,
                {
                    "2234567890123456789": "1234567890123456789",
                    "4234567890123456789": "3234567890123456789",
                },
            )

    def test_duplicate_accepted_dr2_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(LamostGaiaFormError, "repeats a DR2"):
                load_accepted_bridge(self.bridge(Path(temporary), duplicate_dr2=True))


if __name__ == "__main__":
    unittest.main()
