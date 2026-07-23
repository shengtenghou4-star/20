#!/usr/bin/env python3
"""Acquire Dark-668 LAMOST RV epochs through the anonymous browser form.

Coordinates discover nearby public rows in deterministic batches. A row is kept
only when its returned Gaia DR3 character identifier exactly matches an ID in that
same batch. Plaintext IDs, positions, epochs, RVs and errors are source-level
research products and must be encrypted before artifact persistence.
"""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pandas as pd

from hou_compact.gaia import sha256_file
from hou_compact.lamost_form_response import parse_delimited_response, resolve_column
from hou_compact.lamost_form_rv import (
    FormRVBatchReceipt,
    FormRVConfig,
    build_browser_form_fields,
    candidate_safe_form_rv_summary,
    normalize_candidates,
    standardize_exact_rows,
)
from hou_compact.lamost_search_form import submit_search_form

_OUTPUT_COLUMNS = (
    "gaia_source_id",
    "obsid",
    "mjd",
    "rv",
    "rv_err",
    "snrg",
    "snri",
    "snrz",
    "fibermask",
    "class",
    "subclass",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_lamost_form_epochs.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_lamost_form_summary.json"),
    )
    parser.add_argument(
        "--search-url",
        default="https://www.lamost.org/dr8/v2.0/search",
    )
    parser.add_argument(
        "--submit-url",
        default="https://www.lamost.org/dr8/v2.0/q",
    )
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--separation-arcsec", type=float, default=2.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def _chunks(frame: pd.DataFrame, size: int):
    for start in range(0, len(frame), size):
        yield frame.iloc[start : start + size]


def _preflight(opener: object, url: str, timeout: float) -> dict[str, object]:
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "HOU-COMPACT/0.1 Dark-668 form preflight"},
    )
    with opener.open(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        content_type = str(response.headers.get("Content-Type", ""))
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise RuntimeError("search preflight exceeded the byte limit")
    if status != 200:
        raise RuntimeError(f"search preflight returned HTTP {status}")
    return {
        "status": status,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _normalized_output_table(frame: pd.DataFrame) -> pd.DataFrame:
    resolved = {column: resolve_column(frame, column) for column in _OUTPUT_COLUMNS}
    required = {"gaia_source_id", "obsid", "mjd", "rv", "rv_err"}
    missing = sorted(column for column in required if resolved[column] is None)
    if missing:
        raise RuntimeError(f"anonymous form table is missing required columns: {missing}")
    output = pd.DataFrame(index=frame.index)
    for column in _OUTPUT_COLUMNS:
        source = resolved[column]
        output[column] = frame[source] if source is not None else pd.NA
    return output


def _empty_epoch_table() -> pd.DataFrame:
    return standardize_exact_rows(
        pd.DataFrame(columns=_OUTPUT_COLUMNS),
        set(),
    )


def _sanitize_error(error: BaseException) -> str:
    text = " ".join(str(error).split())
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    text = re.sub(r"\b\d{6,}\b", "[number-redacted]", text)
    return text[:1000]


def main() -> None:
    args = parse_args()
    if not math.isfinite(args.request_delay_seconds) or args.request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must be finite and non-negative")
    config = FormRVConfig(
        batch_size=args.batch_size,
        separation_arcsec=args.separation_arcsec,
    )
    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    prepared = normalize_candidates(candidates)
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    preflight: dict[str, object] | None = None
    frames: list[pd.DataFrame] = []
    receipts: list[FormRVBatchReceipt] = []
    seen_obsids: set[int] = set()
    failed_batch_index: int | None = None
    failure: BaseException | None = None
    try:
        preflight = _preflight(opener, args.search_url, args.timeout)
        batches = list(_chunks(prepared, config.batch_size))
        for batch_index, batch in enumerate(batches):
            fields = build_browser_form_fields(
                batch,
                separation_arcsec=config.separation_arcsec,
            )
            body, _, form_receipt = submit_search_form(
                args.submit_url,
                fields,
                timeout=args.timeout,
                opener=opener,
                referer=args.search_url,
            )
            raw = _normalized_output_table(parse_delimited_response(body))
            batch_ids = set(batch["source_id"].astype(int))
            standardized = standardize_exact_rows(raw, batch_ids)
            current_obsids = set(standardized["obsid"].astype(int))
            duplicate = seen_obsids.intersection(current_obsids)
            if duplicate:
                raise RuntimeError(
                    "one LAMOST obsid was returned in multiple exact candidate batches"
                )
            seen_obsids.update(current_obsids)
            frames.append(standardized)
            receipts.append(
                FormRVBatchReceipt(
                    batch_index=batch_index,
                    input_target_count=len(batch),
                    returned_row_count=len(raw),
                    exact_identity_row_count=len(standardized),
                    csv_sha256=hashlib.sha256(body).hexdigest(),
                    form_receipt=form_receipt.to_record(),
                )
            )
            if batch_index + 1 < len(batches) and args.request_delay_seconds:
                time.sleep(args.request_delay_seconds)
    except BaseException as error:
        failed_batch_index = len(receipts)
        failure = error

    epochs = (
        pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else _empty_epoch_table()
    )
    if not epochs.empty:
        epochs = epochs.sort_values(
            ["source_id", "mjd", "obsid"], kind="stable"
        ).reset_index(drop=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    epochs.to_csv(args.output, index=False)

    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "pass" if failure is None else "partial_failure",
        "candidate_input_sha256": sha256_file(args.candidates),
        "release": "dr8/v2.0",
        "transport": "same_origin_cookie_multipart_pipe_table",
        "preflight_receipt": preflight,
        "summary": candidate_safe_form_rv_summary(
            len(prepared),
            epochs,
            receipts,
            config,
        ),
        "batch_receipts": [receipt.to_record() for receipt in receipts],
        "failed_batch_index": failed_batch_index,
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": (
            "Never commit or upload plaintext source IDs, coordinates, epochs, RVs or errors."
        ),
        "identity_contract": (
            "Coordinates discover nearby public rows. Retention requires exact Gaia DR3 "
            "character equality within the same deterministic candidate batch."
        ),
        "interpretation_boundary": (
            "The output is an exact public follow-up dataset, not evidence of variability, "
            "binarity or a compact companion."
        ),
    }
    if failure is not None:
        payload["error_type"] = type(failure).__name__
        payload["error"] = _sanitize_error(failure)
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if failure is not None:
        raise RuntimeError("Dark-668 anonymous form acquisition ended with a partial failure")


if __name__ == "__main__":
    main()
