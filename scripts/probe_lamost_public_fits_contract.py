#!/usr/bin/env python3
"""Probe the anonymous LAMOST ConeSearch-to-FITS RV route.

The official example cone is used to discover one arbitrary public spectrum.
Returned row values are inspected in memory only and are not written to output.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from hou_compact.lamost_conesearch import query_lamost_cone
from hou_compact.lamost_spectrum_fits import (
    download_lamost_spectrum_fits,
    extract_lasp_rv_from_fits,
)

_REQUIRED_DISCOVERY_COLUMNS = {
    "catalogue_gaia_source_id",
    "catalogue_obsid",
    "catalogue_mjd",
    "catalogue_snrg",
    "catalogue_snri",
    "catalogue_snrz",
    "catalogue_fibermask",
    "catalogue_class",
    "catalogue_subclass",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument(
        "--conesearch-endpoint",
        default="https://www.lamost.org/dr8/v2.0/voservice/conesearch",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_public_fits_contract.json"),
    )
    return parser.parse_args()


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(path.read_text(encoding="utf-8"))


def _identity_text(value: object) -> str:
    return value.decode("ascii").strip() if isinstance(value, bytes) else str(value).strip()


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "candidate_safe": True,
        "status": "failure",
        "transport": "anonymous_ivoa_conesearch_plus_public_fits",
        "release": "dr8/v2.0",
        "row_values_persisted": False,
        "claim_boundary": (
            "One arbitrary public example is inspected in memory. No identifiers, "
            "coordinates, spectrum bytes, or radial-velocity values are persisted."
        ),
    }
    try:
        frame, cone_receipt = query_lamost_cone(
            args.conesearch_endpoint,
            ra_deg=10.0004738,
            dec_deg=40.9952444,
            radius_deg=0.2,
            timeout=args.timeout,
        )
        returned = {str(column).lower() for column in frame.columns}
        missing = sorted(_REQUIRED_DISCOVERY_COLUMNS - returned)
        payload.update(
            {
                "cone_row_count": int(len(frame)),
                "returned_columns": sorted(returned),
                "missing_discovery_columns": missing,
                "cone_receipt": cone_receipt.to_record(),
            }
        )
        if missing:
            raise RuntimeError(f"ConeSearch missing columns: {missing}")
        if frame.empty:
            raise RuntimeError("official example cone returned no rows")

        sample = None
        for _, row in frame.iterrows():
            if re.fullmatch(r"[0-9]+", _identity_text(row["catalogue_gaia_source_id"])):
                sample = row
                break
        if sample is None:
            raise RuntimeError("ConeSearch returned no exact-digit Gaia DR3 identity")

        obsid = int(pd.to_numeric(sample["catalogue_obsid"], errors="raise"))
        body, fits_receipt = download_lamost_spectrum_fits(
            args.openapi_root,
            dr_version="dr8",
            sub_version="v2.0",
            obsid=obsid,
            timeout=args.timeout,
        )
        extract_lasp_rv_from_fits(body)
        payload.update(
            {
                "status": "pass",
                "exact_gaia_dr3_identity_present": True,
                "fits_has_finite_rv_and_positive_error": True,
                "fits_receipt": fits_receipt.to_record(),
            }
        )
        _write(args.output, payload)
    except Exception as error:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:2000]
        _write(args.output, payload)
        raise


if __name__ == "__main__":
    main()
