#!/usr/bin/env python3
"""Validate one public DESI DR1 single-epoch RVTAB file.

An arbitrary non-backup coadd row is selected through Astro Data Lab only to
locate one public Healpix file.  Sample identifiers, locator values, file path,
RVs, and uncertainties remain in memory; the persisted receipt contains only
schema names, aggregate row counts, and hashes.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import math
from pathlib import Path

from astropy.io import fits
import numpy as np
import pandas as pd

from hou_compact.datacentral_tap import tap_sync_get
from hou_compact.desi_dr1 import build_sample_query, single_epoch_rvtab_url
from hou_compact.desi_rvtab import download_rvtab_fits, inspect_rvtab_schema
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
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_dr1_single_epoch_contract.json"),
    )
    return parser.parse_args()


def _column(frame: pd.DataFrame, wanted: str) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    if wanted.lower() not in mapping:
        raise RuntimeError(f"DESI sample is missing {wanted}")
    return mapping[wanted.lower()]


def _target_rvtab_contract(body: bytes, targetid: int) -> dict[str, object]:
    with fits.open(
        BytesIO(body),
        memmap=False,
        lazy_load_hdus=False,
        ignore_missing_simple=False,
    ) as hdul:
        if "RVTAB" not in hdul:
            raise RuntimeError("DESI single-epoch file has no RVTAB extension")
        rvtab = hdul["RVTAB"]
        if rvtab.data is None:
            raise RuntimeError("DESI RVTAB extension has no rows")
        names = {str(name).upper() for name in (rvtab.columns.names or [])}
        required = {"TARGETID", "VRAD", "VRAD_ERR", "RVS_WARN", "SUCCESS"}
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"DESI RVTAB is missing columns: {missing}")
        mask = rvtab.data["TARGETID"] == targetid
        matched = rvtab.data[mask]
        if len(matched) < 1:
            raise RuntimeError("sample TARGETID is absent from the located RVTAB file")
        rv = np.asarray(matched["VRAD"], dtype="float64")
        rv_error = np.asarray(matched["VRAD_ERR"], dtype="float64")
        warning = np.asarray(matched["RVS_WARN"])
        success = np.asarray(matched["SUCCESS"]).astype(bool)
        finite_pair = np.isfinite(rv) & np.isfinite(rv_error) & (rv_error > 0)
        quality = finite_pair & (warning == 0) & success
        time_columns = sorted(
            name for name in names if name in {"EXPID", "MJD", "MJD_OBS", "NIGHT"}
        )
        return {
            "rvtab_row_count": int(len(rvtab.data)),
            "sample_target_epoch_count": int(len(matched)),
            "sample_target_finite_rv_positive_error_count": int(finite_pair.sum()),
            "sample_target_quality_pass_count": int(quality.sum()),
            "rvtab_required_columns_present": True,
            "rvtab_time_locator_columns": time_columns,
        }


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "release": "DESI DR1 MWS single-epoch RVTAB",
        "sample_values_persisted": False,
        "backup_program_excluded": True,
        "claim_boundary": (
            "This probe validates one arbitrary public non-backup single-epoch file and "
            "its target/RV/time schema only. It is not a Dark-668 overlap, variability, "
            "binary, compact-object, or novelty result."
        ),
    }
    try:
        sample, tap_receipt = tap_sync_get(
            args.tap_root,
            build_sample_query(),
            maxrec=1,
            timeout=args.timeout,
        )
        if len(sample) != 1:
            raise RuntimeError("DESI sample query did not return exactly one row")
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
        if program == "backup":
            raise RuntimeError("DESI sample unexpectedly used backup program")
        url = single_epoch_rvtab_url(
            args.data_root,
            survey=survey,
            program=program,
            healpix=healpix,
        )
        body, file_receipt = download_rvtab_fits(
            url,
            timeout=args.timeout,
        )
        schema = inspect_rvtab_schema(body)
        contract = _target_rvtab_contract(body, targetid)
        if int(contract["sample_target_finite_rv_positive_error_count"]) < 1:
            raise RuntimeError("sample target has no finite single-epoch RV/error pair")
        if not math.isfinite(float(file_receipt.response_bytes)):
            raise RuntimeError("invalid DESI file-size receipt")

        payload.update(
            {
                "status": "pass",
                "tap_receipt": tap_receipt.to_record(),
                "file_receipt": file_receipt.to_record(),
                "hdu_columns": {
                    name: list(columns) for name, columns in sorted(schema.items())
                },
                **contract,
            }
        )
    except Exception as error:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:1000]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(args.output.read_text(encoding="utf-8"))
    if payload["status"] != "pass":
        raise RuntimeError(
            str(payload.get("error", "DESI single-epoch contract failed"))
        )


if __name__ == "__main__":
    main()
