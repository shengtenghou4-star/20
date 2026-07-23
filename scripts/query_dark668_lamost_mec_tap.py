#!/usr/bin/env python3
"""Query exact Dark-668 LAMOST multiple-epoch rows through OpenAPI SQL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.gaia import sha256_file
from hou_compact.lamost import (
    LamostContractError,
    explode_lrs_multiple_epoch_catalog,
    parse_exact_int_text,
)
from hou_compact.lamost_openapi_sql import OpenAPISQLService
from hou_compact.lamost_tap_mec import (
    candidate_safe_mec_summary,
    discover_mec_table_specs,
    query_exact_mec_rows,
)

_EPOCH_COLUMNS = [
    "dr2_source_id",
    "lamost_source_id",
    "obsid",
    "lmjm",
    "mjd",
    "vrad_list_kms",
    "rv_list_status",
    "observation_index",
    "observation_count",
    "source_match_mode",
    "source_id",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bridge", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_lamost_epochs.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_lamost_mec_tap_summary.json"),
    )
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v1.0")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--maxrec-per-batch", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def _accepted_bridge(path: Path) -> tuple[dict[int, int], dict[str, int]]:
    bridge = pd.read_csv(path, dtype=str)
    required = {"source_id", "dr2_source_id", "dr2_bridge_status"}
    missing = sorted(required - set(bridge.columns))
    if missing:
        raise KeyError(f"bridge is missing columns: {missing}")
    accepted = bridge.loc[
        bridge["dr2_bridge_status"].eq("accepted_unique_or_separated_nearest")
    ].copy()
    accepted["source_id_int"] = [
        parse_exact_int_text(value, name="bridge.source_id")
        for value in accepted["source_id"]
    ]
    accepted["dr2_source_id_int"] = [
        parse_exact_int_text(value, name="bridge.dr2_source_id")
        for value in accepted["dr2_source_id"]
    ]
    if accepted["source_id_int"].duplicated().any():
        raise LamostContractError("accepted bridge contains duplicate Gaia DR3 IDs")
    if accepted["dr2_source_id_int"].duplicated().any():
        raise LamostContractError("accepted bridge reuses a Gaia DR2 ID")
    mapping = dict(
        zip(
            accepted["dr2_source_id_int"].astype(int),
            accepted["source_id_int"].astype(int),
            strict=True,
        )
    )
    counts = {
        str(key): int(value)
        for key, value in bridge["dr2_bridge_status"].value_counts().items()
    }
    return mapping, counts


def _explode_unique_rows(
    rows: pd.DataFrame,
    dr2_to_dr3: dict[int, int],
) -> tuple[pd.DataFrame, int]:
    accepted = rows.loc[
        rows.get("tap_mec_status", pd.Series(dtype=str)).eq("accepted_unique")
    ]
    frames: list[pd.DataFrame] = []
    failures = 0
    for row in accepted.to_dict(orient="records"):
        try:
            epochs = explode_lrs_multiple_epoch_catalog([row])
        except (KeyError, TypeError, ValueError, LamostContractError):
            failures += 1
            continue
        epochs["source_id"] = epochs["dr2_source_id"].map(dr2_to_dr3)
        if epochs["source_id"].isna().any():
            raise RuntimeError("accepted OpenAPI Gaia DR2 ID is absent from bridge map")
        epochs["source_id"] = epochs["source_id"].astype("int64")
        frames.append(epochs)
    if not frames:
        return pd.DataFrame(columns=_EPOCH_COLUMNS), failures
    output = pd.concat(frames, ignore_index=True)
    duplicate = output.duplicated(["source_id", "obsid"])
    if duplicate.any():
        raise LamostContractError(
            f"OpenAPI overlap contains {int(duplicate.sum())} duplicate source/obsid rows"
        )
    return output.sort_values(
        ["source_id", "mjd", "obsid"], kind="stable"
    ).reset_index(drop=True), failures


def main() -> None:
    args = parse_args()
    dr2_to_dr3, bridge_status_counts = _accepted_bridge(args.bridge)
    service = OpenAPISQLService(
        args.openapi_root,
        dr_version=args.dr_version,
        sub_version=args.sub_version,
        timeout=args.timeout,
    )
    specs = discover_mec_table_specs(service)
    selected = specs[0]
    rows, receipts = query_exact_mec_rows(
        service,
        selected,
        dr2_to_dr3.keys(),
        batch_size=args.batch_size,
        maxrec_per_batch=args.maxrec_per_batch,
    )
    epochs, contract_failures = _explode_unique_rows(rows, dr2_to_dr3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    epochs.to_csv(args.output, index=False)

    payload = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "bridge_input_sha256": sha256_file(args.bridge),
        "bridge_accepted_source_count": len(dr2_to_dr3),
        "bridge_status_counts": bridge_status_counts,
        "release": f"{args.dr_version}/{args.sub_version}",
        "sql_endpoint": service.endpoint,
        "transport": "bounded_openapi_sql_get",
        "selected_table": selected.to_record(),
        "mec_summary": candidate_safe_mec_summary(
            len(dr2_to_dr3), rows, specs, receipts
        ),
        "exploded_epoch_rows": int(len(epochs)),
        "exploded_gaia_dr3_sources": (
            int(epochs["source_id"].nunique()) if not epochs.empty else 0
        ),
        "contract_failure_rows": contract_failures,
        "query_receipts": [receipt.to_record() for receipt in receipts],
        "sql_receipts": [receipt.to_record() for receipt in service.receipts],
        "source_level_output_written": True,
        "source_level_output_path": str(args.output),
        "public_commit_policy": (
            "Never commit or upload plaintext SQL rows or exploded source-level epochs."
        ),
        "claim_boundary": (
            "Exact Gaia-release-aware LAMOST multiple-epoch coverage only. No orbit, "
            "binary, or compact-object claim is authorized."
        ),
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
