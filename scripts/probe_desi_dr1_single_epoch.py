#!/usr/bin/env python3
"""Validate the official public DESI DR1 single-epoch RVTAB header contract.

The DESI DR1 MWS documentation publishes a concrete non-backup example file for
commissioning survey ``cmx``, program ``other``, HEALPix 2152.  This probe reads
only its initial FITS header range, never the table data body.  It stores no row
values, target identifiers, coordinates, RVs, or uncertainties.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.desi_fits_prefix import fetch_fits_prefix, parse_rvtab_prefix


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
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--prefix-bytes", type=int, default=128 * 1024)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_dr1_single_epoch_contract.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.3",
        "candidate_safe": True,
        "status": "failure",
        "release": "DESI DR1 MWS single-epoch RVTAB",
        "retrieval_mode": "bounded_http_range_fits_headers_only",
        "example_values_persisted": False,
        "backup_program_excluded": True,
        "claim_boundary": (
            "This probe validates the official public non-backup example RVTAB header "
            "schema only. It does not download row data and is not a Dark-668 overlap, "
            "variability, binary, compact-object, or novelty result."
        ),
    }
    try:
        prefix, receipt = fetch_fits_prefix(
            args.example_url,
            prefix_bytes=args.prefix_bytes,
            timeout=args.timeout,
        )
        contract = parse_rvtab_prefix(prefix)
        columns = set(contract["columns"])
        required = {"TARGETID", "VRAD", "VRAD_ERR", "RVS_WARN", "SUCCESS"}
        missing = sorted(required - columns)
        if missing:
            raise RuntimeError(f"DESI RVTAB is missing columns: {missing}")
        time_columns = sorted(
            name for name in columns if name in {"EXPID", "MJD", "MJD_OBS", "NIGHT"}
        )
        if not time_columns:
            raise RuntimeError("DESI RVTAB has no exposure/time locator column")
        payload.update(
            {
                "status": "pass",
                "prefix_receipt": receipt.to_record(),
                "rvtab_extname": contract["extname"],
                "rvtab_row_bytes": contract["row_bytes"],
                "rvtab_row_count": contract["row_count"],
                "rvtab_field_count": contract["field_count"],
                "rvtab_columns": list(contract["columns"]),
                "rvtab_required_columns_present": True,
                "rvtab_time_locator_columns": time_columns,
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
