#!/usr/bin/env python3
"""Validate the official public DESI DR1 single-epoch RVTAB example.

The DESI DR1 MWS documentation publishes a concrete non-backup example file for
commissioning survey ``cmx``, program ``other``, HEALPix 2152.  This probe uses
that stable example only to freeze the FITS/HDU/column contract.  It stores no
row values, target identifiers, coordinates, RVs, or uncertainties.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path

from astropy.io import fits
import numpy as np

from hou_compact.desi_rvtab import download_rvtab_fits, inspect_rvtab_schema


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--example-url",
        default=(
            "https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0/"
            "rv_output/240521/healpix/cmx/other/21/2152/"
            "rvtab_spectra-cmx-other-2152.fits"
        ),
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_dr1_single_epoch_contract.json"),
    )
    return parser.parse_args()


def _rvtab_contract(body: bytes) -> dict[str, object]:
    with fits.open(
        BytesIO(body),
        memmap=False,
        lazy_load_hdus=False,
        ignore_missing_simple=False,
    ) as hdul:
        if "RVTAB" not in hdul:
            raise RuntimeError("DESI single-epoch file has no RVTAB extension")
        rvtab = hdul["RVTAB"]
        if rvtab.data is None or len(rvtab.data) < 1:
            raise RuntimeError("DESI RVTAB extension has no rows")
        names = {str(name).upper() for name in (rvtab.columns.names or [])}
        required = {"TARGETID", "VRAD", "VRAD_ERR", "RVS_WARN", "SUCCESS"}
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"DESI RVTAB is missing columns: {missing}")
        rv = np.asarray(rvtab.data["VRAD"], dtype="float64")
        rv_error = np.asarray(rvtab.data["VRAD_ERR"], dtype="float64")
        warning = np.asarray(rvtab.data["RVS_WARN"])
        success = np.asarray(rvtab.data["SUCCESS"]).astype(bool)
        finite_pair = np.isfinite(rv) & np.isfinite(rv_error) & (rv_error > 0)
        quality = finite_pair & (warning == 0) & success
        time_columns = sorted(
            name for name in names if name in {"EXPID", "MJD", "MJD_OBS", "NIGHT"}
        )
        return {
            "rvtab_row_count": int(len(rvtab.data)),
            "finite_rv_positive_error_count": int(finite_pair.sum()),
            "quality_pass_count": int(quality.sum()),
            "rvtab_required_columns_present": True,
            "rvtab_time_locator_columns": time_columns,
        }


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "status": "failure",
        "release": "DESI DR1 MWS single-epoch RVTAB",
        "example_values_persisted": False,
        "backup_program_excluded": True,
        "claim_boundary": (
            "This probe validates the official public non-backup example file and its "
            "RVTAB/FIBERMAP/SCORES/GAIA schema only. It is not a Dark-668 overlap, "
            "variability, binary, compact-object, or novelty result."
        ),
    }
    try:
        body, file_receipt = download_rvtab_fits(
            args.example_url,
            timeout=args.timeout,
        )
        schema = inspect_rvtab_schema(body)
        contract = _rvtab_contract(body)
        if int(contract["finite_rv_positive_error_count"]) < 1:
            raise RuntimeError("DESI example contains no finite RV/error pair")
        payload.update(
            {
                "status": "pass",
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
