#!/usr/bin/env python3
"""Validate the public GALAH DR4 per-spectrum TAP contract.

The probe discovers the public per-spectrum table from TAP_SCHEMA, validates the
minimal exact-identity/RV schema, and inspects one arbitrary public row. No
source identifier, coordinate, RV, uncertainty, or spectrum value is persisted.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re

import pandas as pd

from hou_compact.datacentral_tap import DataCentralTapError, tap_sync_get
from hou_compact.galah_dr4 import (
    GalahDR4Error,
    build_sample_query,
    discover_allspec_table,
    validate_allspec_columns,
)
from hou_compact.lamost import parse_exact_int_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tap-root",
        default="https://datacentral.org.au/vo/tap",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/galah_dr4_tap_contract.json"),
    )
    return parser.parse_args()


def _column(frame: pd.DataFrame, wanted: str) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    if wanted.lower() not in mapping:
        raise RuntimeError(f"GALAH sample is missing {wanted}")
    return mapping[wanted.lower()]


def _safe_table_literal(table_name: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.]+", table_name) is None:
        raise ValueError("unsafe GALAH table name")
    return table_name


def _matching_table_names(frame: pd.DataFrame) -> list[str]:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    column = mapping.get("table_name")
    if column is None:
        return []
    return sorted(
        {
            str(value).strip()
            for value in frame[column].dropna()
            if re.fullmatch(r"[A-Za-z0-9_.]+", str(value).strip()) is not None
        }
    )


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "status": "failure",
        "release": "GALAH DR4",
        "transport": "anonymous_datacentral_tap_sync_get",
        "sample_values_persisted": False,
        "claim_boundary": (
            "This probe validates public table identity, schema, transport, and one finite "
            "RV/error pair only. It is not a Dark-668 overlap result, variability claim, "
            "binary classification, compact-object claim, or novelty claim."
        ),
    }
    receipts: list[dict[str, object]] = []
    try:
        tables, receipt = tap_sync_get(
            args.tap_root,
            (
                "SELECT TOP 500 schema_name, table_name FROM TAP_SCHEMA.tables WHERE "
                "schema_name LIKE '%galah%' OR table_name LIKE '%galah%' OR "
                "schema_name LIKE '%GALAH%' OR table_name LIKE '%GALAH%'"
            ),
            maxrec=500,
            timeout=args.timeout,
        )
        receipts.append(receipt.to_record())
        payload["matching_table_names"] = _matching_table_names(tables)
        table_name = discover_allspec_table(tables)
        safe_table = _safe_table_literal(table_name)

        columns, receipt = tap_sync_get(
            args.tap_root,
            (
                "SELECT TOP 2000 column_name, datatype FROM TAP_SCHEMA.columns "
                f"WHERE table_name = '{safe_table}'"
            ),
            maxrec=2000,
            timeout=args.timeout,
        )
        receipts.append(receipt.to_record())
        contract = validate_allspec_columns(columns, table_name)

        sample, receipt = tap_sync_get(
            args.tap_root,
            build_sample_query(table_name),
            maxrec=1,
            timeout=args.timeout,
        )
        receipts.append(receipt.to_record())
        if len(sample) != 1:
            raise RuntimeError("GALAH DR4 sample query did not return exactly one row")

        source_value = sample.iloc[0][_column(sample, "gaiadr3_source_id")]
        parse_exact_int_text(source_value, name="galah.gaiadr3_source_id")
        mjd = float(pd.to_numeric(sample.iloc[0][_column(sample, "mjd")], errors="raise"))
        rv = float(pd.to_numeric(sample.iloc[0][_column(sample, "rv_comp_1")], errors="raise"))
        rv_error = float(
            pd.to_numeric(sample.iloc[0][_column(sample, "e_rv_comp_1")], errors="raise")
        )
        if not math.isfinite(mjd):
            raise RuntimeError("GALAH DR4 sample MJD is not finite")
        if not math.isfinite(rv):
            raise RuntimeError("GALAH DR4 sample RV is not finite")
        if not math.isfinite(rv_error) or rv_error <= 0:
            raise RuntimeError("GALAH DR4 sample RV uncertainty is not finite and positive")

        payload.update(
            {
                "status": "pass",
                "table_name": table_name,
                "validated_required_columns": [
                    "sobject_id",
                    "gaiadr3_source_id",
                    "mjd",
                    "rv_comp_1",
                    "e_rv_comp_1",
                    "flag_sp",
                    "flag_red",
                    "snr_px_ccd3",
                ],
                "available_column_count": len(contract.available_columns),
                "sample_row_count": 1,
                "sample_has_exact_gaia_dr3_identity": True,
                "sample_has_finite_rv_and_positive_error": True,
                "tap_receipts": receipts,
            }
        )
    except (DataCentralTapError, GalahDR4Error, KeyError, TypeError, ValueError, RuntimeError) as error:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:1000]
        payload["tap_receipts"] = receipts

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(args.output.read_text(encoding="utf-8"))
    if payload["status"] != "pass":
        raise RuntimeError(str(payload.get("error", "GALAH DR4 TAP contract failed")))


if __name__ == "__main__":
    main()
