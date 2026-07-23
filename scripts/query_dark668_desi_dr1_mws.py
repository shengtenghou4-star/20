#!/usr/bin/env python3
"""Acquire Dark-668 DESI DR1 MWS coadd rows by exact Gaia DR3 identity.

The public NOIRLab Astro Data Lab table ``desi_dr1.mws`` is queried in bounded
exact-ID batches. Returned rows are retained only when their exact Gaia DR3
identity belongs to the submitted batch and the DESI program is not ``backup``.
The private output supplies TARGETID/HEALPix locators for later single-epoch
RVTAB extraction. Plaintext identities and locators must be encrypted before
artifact persistence.
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
from hou_compact.desi_dr1 import build_exact_id_query, standardize_coadd_rows
from hou_compact.gaia import sha256_file
from hou_compact.lamost_gaia_id_form import normalize_source_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_desi_dr1_mws.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_desi_dr1_mws_summary.json"),
    )
    parser.add_argument(
        "--tap-root",
        default="https://datalab.noirlab.edu/tap",
    )
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


def _safe_counts(rows: pd.DataFrame, column: str) -> dict[str, int]:
    if rows.empty or column not in rows.columns:
        return {}
    values = rows[column].astype("string").fillna("missing")
    return {
        str(key): int(value)
        for key, value in values.value_counts(dropna=False).sort_index().items()
    }


def _candidate_safe_summary(
    target_count: int,
    rows: pd.DataFrame,
    receipts: list[DataCentralTapReceipt],
    *,
    batch_size: int,
) -> dict[str, object]:
    matched_sources = int(rows["source_id"].nunique()) if not rows.empty else 0
    success = rows.get(
        "success", pd.Series(False, index=rows.index)
    ).astype(bool)
    file_keys = (
        rows.loc[:, ["survey", "program", "healpix"]].drop_duplicates()
        if not rows.empty
        else pd.DataFrame(columns=["survey", "program", "healpix"])
    )
    return {
        "target_count": int(target_count),
        "matched_source_count": matched_sources,
        "unmatched_source_count": int(target_count - matched_sources),
        "exact_identity_coadd_rows": int(len(rows)),
        "quality_pass_coadd_rows": int(success.sum()),
        "unique_nonbackup_rvtab_file_count": int(len(file_keys)),
        "survey_counts": _safe_counts(rows, "survey"),
        "program_counts": _safe_counts(rows, "program"),
        "request_count": len(receipts),
        "batch_size": int(batch_size),
        "identity_contract": (
            "Exact Gaia DR3 integer constraints against desi_dr1.mws; returned rows are "
            "retained only when their exact identity belongs to the submitted batch."
        ),
        "program_policy": (
            "DESI program=backup is excluded because DR1 documents substantial radial-"
            "velocity systematics for backup targets."
        ),
        "locator_policy": (
            "TARGETID, survey, program, HEALPix and source-file values remain encrypted. "
            "The public receipt exposes only aggregate counts."
        ),
        "claim_boundary": (
            "Coadded coverage and locator counts are not single-epoch variability, orbit, "
            "binary, compact-object, or novelty evidence."
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
    seen_targetids: set[int] = set()
    failed_batch_index: int | None = None
    failure: BaseException | None = None
    batches = list(_chunks(source_ids, args.batch_size))

    try:
        for batch_index, batch_ids in enumerate(batches):
            frame, receipt = tap_sync_get(
                args.tap_root,
                build_exact_id_query(batch_ids),
                maxrec=args.maxrec_per_batch,
                timeout=args.timeout,
            )
            standardized = standardize_coadd_rows(frame, batch_ids)
            current_targetids = set(standardized["targetid"].astype(int))
            if seen_targetids.intersection(current_targetids):
                raise RuntimeError(
                    "one DESI TARGETID was returned in multiple exact-ID batches"
                )
            seen_targetids.update(current_targetids)
            frames.append(standardized)
            receipts.append(receipt)
            if batch_index + 1 < len(batches) and args.request_delay_seconds:
                time.sleep(args.request_delay_seconds)
    except BaseException as error:
        failed_batch_index = len(receipts)
        failure = error

    rows = (
        pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else pd.DataFrame(
            columns=[
                "source_id",
                "targetid",
                "healpix",
                "survey",
                "program",
                "srcfile",
                "vrad",
                "vrad_err",
                "rvs_warn",
                "success",
                "sn_b",
                "sn_r",
                "sn_z",
            ]
        )
    )
    if not rows.empty:
        rows = rows.sort_values(
            ["source_id", "survey", "program", "healpix", "targetid"],
            kind="stable",
        ).reset_index(drop=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(args.output, index=False)

    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "pass" if failure is None else "partial_failure",
        "candidate_input_sha256": sha256_file(args.candidates),
        "release": "DESI DR1 MWS VAC",
        "transport": "anonymous_noirlab_tap_exact_gaia_id_batches",
        "summary": _candidate_safe_summary(
            len(source_ids),
            rows,
            receipts,
            batch_size=args.batch_size,
        ),
        "batch_receipts": [receipt.to_record() for receipt in receipts],
        "failed_batch_index": failed_batch_index,
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": (
            "Never commit or upload plaintext Gaia IDs, TARGETIDs, HEALPix locators, "
            "source filenames, or target-level coadd measurements."
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
        raise RuntimeError("Dark-668 DESI DR1 MWS acquisition ended with a partial failure")


if __name__ == "__main__":
    main()
