from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request

from hou_compact.lamost_form_rv import LamostFormError, acquire_form_rv


class FakeResponse(io.BytesIO):
    def __init__(
        self,
        payload: bytes,
        *,
        url: str,
        status: int = 200,
        content_type: str = "text/plain",
    ) -> None:
        super().__init__(payload)
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._url = url

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
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

    def open(self, request: Request, timeout: float) -> FakeResponse:
        if not self.calls:
            raise AssertionError("unexpected opener call")
        expected = self.calls.pop(0)
        self.requests.append(request)
        if request.get_method() != expected.method:
            raise AssertionError(
                f"expected method {expected.method}, got {request.get_method()}"
            )
        if request.full_url != expected.url:
            raise AssertionError(f"expected URL {expected.url}, got {request.full_url}")
        if timeout <= 0:
            raise AssertionError("timeout must be positive")
        return expected.response


class LamostFormRVTests(unittest.TestCase):
    SEARCH = "https://www.lamost.org/dr8/v1.0/search"
    ACTION = "https://www.lamost.org/dr8/v1.0/q"
    HEADER = (
        "obsid,lmjd,mjd,obsdate,rv,rv_err,snrg,snri,class,subclass,"
        "fibermask,gaia_source_id\n"
    )

    def input_csv(self, directory: Path, obsids: list[str]) -> Path:
        path = directory / "input.csv"
        path.write_text(
            "obsid\n" + "".join(f"{obsid}\n" for obsid in obsids),
            encoding="utf-8",
        )
        return path

    def run_client(
        self,
        directory: Path,
        obsids: list[str],
        opener: FakeOpener,
        *,
        batch_size: int = 100,
    ):
        output = directory / "rows.csv"
        private_manifest = directory / "private.json"
        safe_summary = directory / "safe.json"
        result = acquire_form_rv(
            obsid_input=self.input_csv(directory, obsids),
            output_path=output,
            private_manifest_path=private_manifest,
            safe_summary_path=safe_summary,
            search_url=self.SEARCH,
            action_url=self.ACTION,
            batch_size=batch_size,
            retries=1,
            opener=opener,
            sleep=lambda _seconds: None,
        )
        return result, output, private_manifest, safe_summary

    def search_call(self) -> ExpectedCall:
        return ExpectedCall(
            "GET",
            self.SEARCH,
            FakeResponse(
                b"<html><form></form></html>",
                url=self.SEARCH,
                content_type="text/html",
            ),
        )

    def test_direct_csv_response_is_validated_and_written(self) -> None:
        csv_payload = (
            self.HEADER
            + "1001,59000,59000.1,2020-01-01,10.5,1.2,20,18,STAR,G2,0,123\n"
            + "1002,59001,59001.1,2020-01-02,30.5,2.0,12,11,STAR,K1,0,456\n"
        ).encode("utf-8")
        opener = FakeOpener(
            [
                self.search_call(),
                ExpectedCall(
                    "POST",
                    self.ACTION,
                    FakeResponse(
                        csv_payload,
                        url=self.ACTION,
                        content_type="text/csv",
                    ),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result, output, private_manifest, safe_summary = self.run_client(
                directory,
                ["1001", "1002"],
                opener,
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["returned_unique_obsids"], 2)
            rows = list(csv.DictReader(output.open("r", encoding="utf-8")))
            self.assertEqual([row["obsid"] for row in rows], ["1001", "1002"])
            private = json.loads(private_manifest.read_text(encoding="utf-8"))
            self.assertEqual(private["batches"][0]["source_kind"], "form_post")
            safe_text = safe_summary.read_text(encoding="utf-8")
            self.assertNotIn("1001", safe_text)
            self.assertNotIn("1002", safe_text)
            self.assertFalse(opener.calls)

    def test_html_response_follows_only_same_origin_csv_link(self) -> None:
        download = "https://www.lamost.org/dr8/v1.0/download/result.csv?token=abc"
        html = (
            '<html><a href="https://evil.example/result.csv">evil</a>'
            '<a href="/dr8/v1.0/download/result.csv?token=abc">download</a></html>'
        ).encode("utf-8")
        csv_payload = (
            self.HEADER
            + "1001,59000,59000.1,2020-01-01,10.5,1.2,20,18,STAR,G2,0,123\n"
        ).encode("utf-8")
        opener = FakeOpener(
            [
                self.search_call(),
                ExpectedCall(
                    "POST",
                    self.ACTION,
                    FakeResponse(html, url=self.ACTION, content_type="text/html"),
                ),
                ExpectedCall(
                    "GET",
                    download,
                    FakeResponse(csv_payload, url=download, content_type="text/csv"),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            result, _, private_manifest, _ = self.run_client(
                Path(temporary), ["1001"], opener
            )
            self.assertEqual(result["returned_unique_obsids"], 1)
            private = json.loads(private_manifest.read_text(encoding="utf-8"))
            transport = private["batches"][0]["transport"]
            self.assertEqual(transport[-1]["kind"], "same_origin_followup")
            self.assertNotIn("token=abc", json.dumps(private))
            self.assertFalse(opener.calls)

    def test_out_of_batch_obsid_fails_and_deletes_output(self) -> None:
        csv_payload = (
            self.HEADER
            + "9999,59000,59000.1,2020-01-01,10.5,1.2,20,18,STAR,G2,0,123\n"
        ).encode("utf-8")
        opener = FakeOpener(
            [
                self.search_call(),
                ExpectedCall(
                    "POST",
                    self.ACTION,
                    FakeResponse(csv_payload, url=self.ACTION, content_type="text/csv"),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(LamostFormError, "outside the batch"):
                self.run_client(directory, ["1001"], opener)
            self.assertFalse((directory / "rows.csv").exists())
            safe_text = (directory / "safe.json").read_text(encoding="utf-8")
            self.assertNotIn("9999", safe_text)
            self.assertNotIn("1001", safe_text)

    def test_duplicate_response_obsid_fails_closed(self) -> None:
        csv_payload = (
            self.HEADER
            + "1001,59000,59000.1,2020-01-01,10,1,20,18,STAR,G2,0,123\n"
            + "1001,59000,59000.1,2020-01-01,11,1,20,18,STAR,G2,0,123\n"
        ).encode("utf-8")
        opener = FakeOpener(
            [
                self.search_call(),
                ExpectedCall(
                    "POST",
                    self.ACTION,
                    FakeResponse(csv_payload, url=self.ACTION, content_type="text/csv"),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(LamostFormError, "repeats an obsid"):
                self.run_client(Path(temporary), ["1001"], opener)

    def test_header_drift_between_batches_fails_closed(self) -> None:
        first = (
            self.HEADER
            + "1001,59000,59000.1,2020-01-01,10,1,20,18,STAR,G2,0,123\n"
        ).encode("utf-8")
        second = b"obsid,rv,rv_err,fibermask\n1002,20,2,0\n"
        opener = FakeOpener(
            [
                self.search_call(),
                ExpectedCall(
                    "POST",
                    self.ACTION,
                    FakeResponse(first, url=self.ACTION, content_type="text/csv"),
                ),
                ExpectedCall(
                    "POST",
                    self.ACTION,
                    FakeResponse(second, url=self.ACTION, content_type="text/csv"),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(LamostFormError, "header changed"):
                self.run_client(
                    Path(temporary), ["1001", "1002"], opener, batch_size=1
                )

    def test_duplicate_input_obsid_is_rejected_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            opener = FakeOpener([])
            with self.assertRaisesRegex(LamostFormError, "repeats an obsid"):
                self.run_client(directory, ["1001", "1001"], opener)
            self.assertFalse(opener.requests)


if __name__ == "__main__":
    unittest.main()
