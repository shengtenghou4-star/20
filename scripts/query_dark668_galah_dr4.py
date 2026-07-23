#!/usr/bin/env python3
"""Acquire Dark-668 GALAH DR4 per-spectrum RV epochs by exact Gaia DR3 ID.

The public Data Central TAP service is queried in bounded batches against the
frozen ``galah_dr4.mainspectable`` table.  Returned rows are retained only when
their exact Gaia DR3 integer identity belongs to the submitted batch.  Plaintext
identifiers and RV products must be encrypted before artifact persistence.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import time

import pandas as pd

from hou_compact.datacentral_tap import DataCentralTapReceipt, tap_sync_get
from hou_compact.gaia import sha256_file
from hou_compact.galah_dr4 import build_exact_id_query, standardize_exact_rows
from hou_compact.lamost_gaia_id_form import normalize_source_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_galah_dr4_epochs.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_galah_dr4_summary.json"),
    )
    parser.add_argument(
        "--tap-root",
        default="https://datacentral.org.au/vo/tap",
    )
    parser.add_argument("--table-name", default="galah_dr4.mainspectable")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--maxrec-per-batch", type=int, default=5000)
    parser.add_argument("--request-delay-seconds", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def _chunks(values: list[int], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _sanitize_error(error: BaseException) -> str:
    text = " ".join(str(error).split())
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    text = re.sub(r"\b\d{6,}\b", "[number-redacted]", text)
    return text[:1000]


def _candidate_safe_summary(
    target_count: int,
    epochs: pd.DataFrame,
    receipts: list[DataCentralTapReceipt],
    *,
    batch_size: int,
    table_name: str,
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
        "target_count": int(target_count),
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
        "batch_size": int(batch_size),
        "table_name": table_name,
        "identity_contract": (
            "Exact Gaia DR3 integer constraints against the public GALAH DR4 per-spectrum "
            "table; returned rows are retained only when their exact identity belongs to "
            "the submitted batch."
        ),
        "quality_contract": (
            "Finite MJD/RV/positive quoted error, flag_sp=0, flag_red=0, and CCD3 S/N>30."
        ),
        "cross_survey_policy": (
            "GALAH RV values are audited independently. They are not numerically merged "
            "with LAMOST until survey-specific zero-point and nuisance-offset controls are "
            "implemented."
        ),
        "claim_boundary": (
            "Coverage and raw RV epochs are not evidence of orbital coherence, binarity, "
            "a compact companion, or novelty."
        ),
    }


def main() -> None:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 50:
        raise ValueError("batch_size must lie in [1, 50]")
    if args.maxrec_per_batch < 1:
        raise ValueError("maxrec_per_batch must be positive")
    if not math.isfinite(args.request_delay_seconds) or args.request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must be finite and non-negative")

    candidates = pd.read_csv(args.candidates, dtype={"source_id": "string"})
    if "source_id" not in candidates.columns:
        raise KeyError("candidates are missing source_id")
    source_ids = normalize_source_ids(candidates["source_id"])
    if not source_ids:
        raise ValueError("candidate input is empty")

    frames: list[pd.DataFrame] = []
    receipts: list[DataCentralTapReceipt] = []
    seen_obsids: set[int] = set()
    failed_batch_index: int | None = None
    failure: BaseException | None = None
    batches = list(_chunks(source_ids, args.batch_size))

    try:
        for batch_index, batch_ids in enumerate(batches):
            frame, receipt = tap_sync_get(
                args.tap_root,
                build_exact_id_query(args.table_name, batch_ids),
                maxrec=args.maxrec_per_batch,
                timeout=args.timeout,
            )
            epochs = standardize_exact_rows(frame, batch_ids)
            current_obsids = set(epochs["obsid"].astype(int))
            if seen_obsids.intersection(current_obsids):
                raise RuntimeError(
                    "one GALAH sobject_id was returned in multiple exact-ID batches"
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
        "release": "GALAH DR4",
        "transport": "anonymous_datacentral_tap_exact_gaia_id_batches",
        "summary": _candidate_safe_summary(
            len(source_ids),
            epochs,
            receipts,
            batch_size=args.batch_size,
            table_name=args.table_name,
        ),
        "batch_receipts": [receipt.to_record() for receipt in receipts],
        "failed_batch_index": failed_batch_index,
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": (
            "Never commit or upload plaintext source IDs, epochs, RVs, uncertainties, "
            "or target-level overlap records."
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
        raise RuntimeError("Dark-668 GALAH DR4 acquisition ended with a partial failure")


if __name__ == "__main__":
    main()
