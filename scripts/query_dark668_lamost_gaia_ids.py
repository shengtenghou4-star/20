#!/usr/bin/env python3
"""Acquire Dark-668 LAMOST RV epochs by native Gaia DR3 ID constraints.

The LAMOST DR8 v2.0 public search accepts a list of Gaia DR3 source IDs through
``gaiasourcearea``.  This route avoids positional cones entirely and retains
only rows whose returned digit-string identity exactly belongs to the submitted
batch.  Plaintext identifiers and RV products must be encrypted before artifact
persistence.
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
from hou_compact.lamost_gaia_id_form import (
    GaiaIDFormReceipt,
    build_gaia_id_form_fields,
    normalize_source_ids,
    standardize_gaia_id_response,
)
from hou_compact.lamost_search_form import submit_search_form


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_lamost_gaia_id_epochs.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_lamost_gaia_id_summary.json"),
    )
    parser.add_argument(
        "--search-url",
        default="https://www.lamost.org/dr8/v2.0/search",
    )
    parser.add_argument(
        "--submit-url",
        default="https://www.lamost.org/dr8/v2.0/q",
    )
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--request-delay-seconds", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args()


def _chunks(values: list[int], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _preflight(opener: object, url: str, timeout: float) -> dict[str, object]:
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "HOU-COMPACT/0.1 Gaia-ID form preflight"},
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


def _sanitize_error(error: BaseException) -> str:
    text = " ".join(str(error).split())
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    text = re.sub(r"\b\d{6,}\b", "[number-redacted]", text)
    return text[:1000]


def _safe_summary(
    target_count: int,
    epochs: pd.DataFrame,
    receipts: list[GaiaIDFormReceipt],
    *,
    batch_size: int,
) -> dict[str, object]:
    source_counts = (
        epochs.groupby("source_id", sort=False).size()
        if not epochs.empty
        else pd.Series(dtype=int)
    )
    success = epochs.get(
        "success", pd.Series(False, index=epochs.index)
    ).astype(bool)
    clean_counts = (
        epochs.loc[success].groupby("source_id", sort=False).size()
        if success.any()
        else pd.Series(dtype=int)
    )
    return {
        "target_count": target_count,
        "matched_source_count": int(len(source_counts)),
        "unmatched_source_count": int(target_count - len(source_counts)),
        "exact_identity_epoch_rows": int(len(epochs)),
        "quality_pass_epoch_rows": int(success.sum()),
        "raw_epoch_threshold_counts": {
            "ge_2": int(source_counts.ge(2).sum()),
            "ge_3": int(source_counts.ge(3).sum()),
            "ge_5": int(source_counts.ge(5).sum()),
            "ge_7": int(source_counts.ge(7).sum()),
            "ge_10": int(source_counts.ge(10).sum()),
        },
        "quality_pass_threshold_counts": {
            "ge_2": int(clean_counts.ge(2).sum()),
            "ge_3": int(clean_counts.ge(3).sum()),
            "ge_5": int(clean_counts.ge(5).sum()),
            "ge_7": int(clean_counts.ge(7).sum()),
            "ge_10": int(clean_counts.ge(10).sum()),
        },
        "request_count": len(receipts),
        "batch_size": batch_size,
        "identity_contract": (
            "Native Gaia DR3 ID list constraint with exact returned character equality; "
            "no coordinate discovery, DR2 bridge, float identity or approximate match."
        ),
        "claim_boundary": (
            "This is public RV coverage data, not evidence of variability, binarity, a "
            "compact companion or novelty."
        ),
    }


def main() -> None:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 1_000_000:
        raise ValueError("batch_size must lie in [1, 1000000]")
    if not math.isfinite(args.request_delay_seconds) or args.request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must be finite and non-negative")

    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    if "source_id" not in candidates.columns:
        raise KeyError("candidates are missing source_id")
    source_ids = normalize_source_ids(candidates["source_id"])
    if not source_ids:
        raise ValueError("candidate input is empty")

    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    preflight: dict[str, object] | None = None
    frames: list[pd.DataFrame] = []
    receipts: list[GaiaIDFormReceipt] = []
    seen_obsids: set[int] = set()
    failed_batch_index: int | None = None
    failure: BaseException | None = None

    try:
        preflight = _preflight(opener, args.search_url, args.timeout)
        batches = list(_chunks(source_ids, args.batch_size))
        for batch_index, batch_ids in enumerate(batches):
            body, _, form_receipt = submit_search_form(
                args.submit_url,
                build_gaia_id_form_fields(batch_ids),
                timeout=args.timeout,
                opener=opener,
                referer=args.search_url,
            )
            epochs, receipt = standardize_gaia_id_response(
                body,
                batch_ids,
                form_receipt,
            )
            current_obsids = set(epochs["obsid"].astype(int))
            if seen_obsids.intersection(current_obsids):
                raise RuntimeError(
                    "one LAMOST obsid was returned in multiple Gaia-ID batches"
                )
            seen_obsids.update(current_obsids)
            frames.append(epochs)
            receipts.append(receipt)
            if batch_index + 1 < len(batches) and args.request_delay_seconds:
                time.sleep(args.request_delay_seconds)
    except BaseException as error:
        failed_batch_index = len(receipts)
        failure = error

    epochs = (
        pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else pd.DataFrame(
            columns=[
                "source_id",
                "obsid",
                "expid",
                "mjd",
                "vrad",
                "vrad_err",
                "success",
                "rvs_warn",
                "fiberstatus",
                "sn_b",
                "sn_r",
                "sn_z",
                "survey",
                "program",
                "source_match_mode",
                "class",
                "subclass",
            ]
        )
    )
    if not epochs.empty:
        epochs = epochs.sort_values(
            ["source_id", "mjd", "obsid"], kind="stable"
        ).reset_index(drop=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    epochs.to_csv(args.output, index=False)

    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "pass" if failure is None else "partial_failure",
        "candidate_input_sha256": sha256_file(args.candidates),
        "release": "dr8/v2.0",
        "transport": "same_origin_cookie_multipart_native_gaia_id_list",
        "preflight_receipt": preflight,
        "summary": _safe_summary(
            len(source_ids),
            epochs,
            receipts,
            batch_size=args.batch_size,
        ),
        "batch_receipts": [receipt.to_record() for receipt in receipts],
        "failed_batch_index": failed_batch_index,
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": (
            "Never commit or upload plaintext source IDs, epochs, RVs or errors."
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
        raise RuntimeError("Dark-668 Gaia-ID acquisition ended with a partial failure")


if __name__ == "__main__":
    main()
