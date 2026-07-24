#!/usr/bin/env python3
"""Retrieve and audit Gaia DR3-to-DR2 identifiers for DESI REF_ID recovery."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.gaia import sha256_file
from hou_compact.gaia_dr2_bridge import GaiaDr2BridgeConfig
from hou_compact.gaia_dr2_bridge_v2 import (
    audit_gaia_dr2_bridge_v2,
    query_gaia_dr2_neighbourhood_v2,
)

_LONG_INTEGER = re.compile(r"(?<![0-9])[0-9]{10,20}(?![0-9])")
_URL = re.compile(r"https?://\S+")


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def failure_manifest_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".failure.manifest.json")


def _sanitized_error_message(error: BaseException) -> str:
    message = _LONG_INTEGER.sub("<redacted-id>", str(error))
    message = _URL.sub("<redacted-url>", message)
    return message[:2000]


def write_failure_manifest(
    *,
    output: Path,
    error: BaseException,
    input_source_count: int | None,
    batch_size: int,
    maxrec_per_batch: int,
    query_retries: int,
    retry_backoff_seconds: float,
) -> dict[str, object]:
    """Persist a candidate-safe bridge failure receipt and return it."""
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "stage": "dr3_dr2_bridge",
        "error_type": type(error).__name__,
        "error_message": _sanitized_error_message(error),
        "input_source_count": input_source_count,
        "settings": {
            "batch_size": batch_size,
            "maxrec_per_batch": maxrec_per_batch,
            "query_retries_per_batch": query_retries,
            "retry_backoff_seconds": retry_backoff_seconds,
        },
        "claim_boundary": (
            "Candidate-safe external-stage failure only; no Gaia source identifier, "
            "coordinate, neighbour row, query text, or candidate classification is disclosed."
        ),
    }
    path = failure_manifest_path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path, help="Gaia DR3 seed table containing source_id")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/gaia_dr2_bridge.csv"),
        help="audited one-row-per-DR3-source bridge",
    )
    parser.add_argument(
        "--neighbourhood-output",
        type=Path,
        help="raw all-neighbour table; defaults beside --output",
    )
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--maxrec-per-batch", type=int, default=5000)
    parser.add_argument("--query-retries", type=int, default=4)
    parser.add_argument("--retry-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--maximum-nearest-distance-mas", type=float, default=1000.0)
    parser.add_argument("--minimum-distance-margin-mas", type=float, default=5.0)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing bridge, neighbourhood, manifest, and failure outputs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if isinstance(args.query_retries, bool) or args.query_retries < 0:
        raise ValueError("query_retries must be non-negative")
    if not math.isfinite(args.retry_backoff_seconds) or args.retry_backoff_seconds < 0:
        raise ValueError("retry_backoff_seconds must be finite and non-negative")

    neighbourhood_output = args.neighbourhood_output or args.output.with_name(
        args.output.stem + ".neighbourhood.csv"
    )
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    failure_path = failure_manifest_path(args.output)
    output_paths = (args.output, neighbourhood_output, manifest_path, failure_path)
    existing = [str(path) for path in output_paths if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError(
            "Gaia DR2 bridge outputs already exist; pass --overwrite to replace them: "
            + ", ".join(existing)
        )
    if args.overwrite:
        for path in output_paths:
            path.unlink(missing_ok=True)

    input_source_count: int | None = None
    try:
        gaia = read_table(args.gaia)
        if "source_id" not in gaia.columns:
            raise KeyError("Gaia input has no source_id column")
        source_ids = pd.to_numeric(gaia["source_id"], errors="raise").astype("int64")
        if source_ids.duplicated().any():
            raise ValueError("Gaia input contains duplicate source_id rows")
        input_source_count = int(source_ids.nunique())

        config = GaiaDr2BridgeConfig(
            batch_size=args.batch_size,
            maxrec_per_batch=args.maxrec_per_batch,
        )
        neighbours, receipts = query_gaia_dr2_neighbourhood_v2(
            source_ids,
            config=config,
            query_retries=args.query_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )
        audited = audit_gaia_dr2_bridge_v2(
            neighbours,
            maximum_nearest_distance_mas=args.maximum_nearest_distance_mas,
            minimum_distance_margin_mas=args.minimum_distance_margin_mas,
        )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        neighbourhood_output.parent.mkdir(parents=True, exist_ok=True)
        neighbours.to_csv(neighbourhood_output, index=False)
        audited.to_csv(args.output, index=False)

        status_counts = {
            str(key): int(value)
            for key, value in audited["dr2_bridge_status"].value_counts().items()
        }
        manifest = {
            "gaia_input": str(args.gaia),
            "gaia_input_sha256": sha256_file(args.gaia),
            "input_source_count": input_source_count,
            "neighbourhood_output": str(neighbourhood_output),
            "neighbourhood_output_sha256": sha256_file(neighbourhood_output),
            "neighbourhood_rows": len(neighbours),
            "neighbourhood_source_count": (
                int(neighbours["dr3_source_id"].nunique()) if not neighbours.empty else 0
            ),
            "output": str(args.output),
            "output_sha256": sha256_file(args.output),
            "audited_rows": len(audited),
            "status_counts": status_counts,
            "accepted_source_count": int(
                audited["dr2_bridge_status"]
                .eq("accepted_unique_or_separated_nearest")
                .sum()
            ),
            "settings": {
                "batch_size": config.batch_size,
                "maxrec_per_batch": config.maxrec_per_batch,
                "query_retries_per_batch": args.query_retries,
                "retry_backoff_seconds": args.retry_backoff_seconds,
                "maximum_nearest_distance_mas": args.maximum_nearest_distance_mas,
                "minimum_distance_margin_mas": args.minimum_distance_margin_mas,
                "server_ordering": "plain_columns_only",
                "client_tie_break": "absolute_magnitude_difference",
                "audit_tie_break": "absolute_magnitude_difference",
            },
            "batch_receipts": [receipt.to_record() for receipt in receipts],
            "interpretation_boundary": (
                "The bridge connects Gaia release identifiers. Acceptance does not prove that "
                "a DESI spectrum belongs to the DR3 source until exact FIBERMAP REF_CAT='G2' "
                "and REF_ID equality is demonstrated."
            ),
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        failure_path.unlink(missing_ok=True)
        print(json.dumps(manifest, indent=2, sort_keys=True))
    except BaseException as error:
        write_failure_manifest(
            output=args.output,
            error=error,
            input_source_count=input_source_count,
            batch_size=args.batch_size,
            maxrec_per_batch=args.maxrec_per_batch,
            query_retries=args.query_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )
        raise


if __name__ == "__main__":
    main()
