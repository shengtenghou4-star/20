#!/usr/bin/env python3
"""Validate the public DESI DR1 MWS exact-identity and locator contract.

The probe inspects Astro Data Lab metadata and one arbitrary non-backup public
row.  No Gaia ID, TARGETID, HEALPix, filename, coordinate, RV, or uncertainty
value is persisted in the candidate-safe receipt.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from hou_compact.datacentral_tap import DataCentralTapError, tap_sync_get
from hou_compact.desi_dr1 import (
    DesiDR1Error,
    build_sample_query,
    single_epoch_rvtab_url,
    validate_mws_columns,
)
from hou_compact.lamost import parse_exact_int_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tap-root",
        default="https://datalab.noirlab.edu/tap",
    )
    parser.add_argument(
        "--data-root",
        default="https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_dr1_mws_tap_contract.json"),
    )
    return parser.parse_args()


def _column(frame: pd.DataFrame, wanted: str) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    if wanted.lower() not in mapping:
        raise RuntimeError(f"DESI sample is missing {wanted}")
    return mapping[wanted.lower()]


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "release": "DESI DR1 MWS VAC",
        "transport": "anonymous_noirlab_astro_datalab_tap_sync_get",
        "sample_values_persisted": False,
        "backup_program_excluded": True,
        "claim_boundary": (
            "This probe validates the public coadded table, exact Gaia DR3 identity, "
            "single-epoch locator fields, and one finite coadd RV/error pair only. It is "
            "not a Dark-668 overlap result, single-epoch RV result, variability claim, "
            "binary classification, compact-object claim, or novelty claim."
        ),
    }
    receipts: list[dict[str, object]] = []
    try:
        columns, receipt = tap_sync_get(
            args.tap_root,
            (
                "SELECT TOP 1000 column_name, datatype FROM TAP_SCHEMA.columns "
                "WHERE table_name = 'desi_dr1.mws'"
            ),
            maxrec=1000,
            timeout=args.timeout,
        )
        receipts.append(receipt.to_record())
        contract = validate_mws_columns(columns)

        sample, receipt = tap_sync_get(
            args.tap_root,
            build_sample_query(),
            maxrec=1,
            timeout=args.timeout,
        )
        receipts.append(receipt.to_record())
        if len(sample) != 1:
            raise RuntimeError("DESI MWS sample query did not return exactly one row")
        row = sample.iloc[0]
        parse_exact_int_text(row[_column(sample, "source_id")], name="desi.source_id")
        targetid = parse_exact_int_text(
            row[_column(sample, "targetid")], name="desi.targetid"
        )
        healpix = parse_exact_int_text(
            row[_column(sample, "healpix")], name="desi.healpix"
        )
        survey = str(row[_column(sample, "survey")]).strip().lower()
        program = str(row[_column(sample, "program")]).strip().lower()
        rv = float(pd.to_numeric(row[_column(sample, "vrad")], errors="raise"))
        rv_error = float(
            pd.to_numeric(row[_column(sample, "vrad_err")], errors="raise")
        )
        warning = int(
            pd.to_numeric(row[_column(sample, "rvs_warn")], errors="raise")
        )
        success = int(
            pd.to_numeric(row[_column(sample, "success")], errors="raise")
        )
        if targetid < 0 or healpix < 0:
            raise RuntimeError("DESI sample locator integers are invalid")
        if program == "backup":
            raise RuntimeError("DESI sample unexpectedly used the excluded backup program")
        if not math.isfinite(rv):
            raise RuntimeError("DESI sample RV is not finite")
        if not math.isfinite(rv_error) or rv_error <= 0:
            raise RuntimeError("DESI sample RV uncertainty is not finite and positive")
        if warning != 0 or success != 1:
            raise RuntimeError("DESI sample does not pass the frozen coadd quality gate")
        single_epoch_rvtab_url(
            args.data_root,
            survey=survey,
            program=program,
            healpix=healpix,
        )

        payload.update(
            {
                "status": "pass",
                "table_name": contract.table_name,
                "available_column_count": len(contract.available_columns),
                "validated_required_columns": [
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
                ],
                "sample_row_count": 1,
                "sample_has_exact_gaia_dr3_identity": True,
                "sample_has_valid_targetid_healpix_locator": True,
                "sample_has_finite_coadd_rv_and_positive_error": True,
                "single_epoch_url_constructible": True,
                "tap_receipts": receipts,
            }
        )
    except (
        DataCentralTapError,
        DesiDR1Error,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
    ) as error:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:1000]
        payload["tap_receipts"] = receipts

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(args.output.read_text(encoding="utf-8"))
    if payload["status"] != "pass":
        raise RuntimeError(str(payload.get("error", "DESI DR1 MWS TAP contract failed")))


if __name__ == "__main__":
    main()
