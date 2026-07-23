#!/usr/bin/env python3
"""Probe the anonymous LAMOST ConeSearch-to-FITS RV route.

The official example cone is used to discover one arbitrary public spectrum with
normalized flux, which is the release flag for an available parameter extension.
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
    LamostSpectrumFITSError,
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
    "catalogue_with_norm_flux",
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


def _text(value: object) -> str:
    return value.decode("utf-8", errors="replace").strip() if isinstance(value, bytes) else str(value).strip()


def _select_parameter_sample(frame: pd.DataFrame) -> tuple[pd.Series, int]:
    exact_identity = frame["catalogue_gaia_source_id"].map(
        lambda value: re.fullmatch(r"[0-9]+", _identity_text(value)) is not None
    )
    normalized = pd.to_numeric(
        frame["catalogue_with_norm_flux"], errors="coerce"
    ).eq(1)
    stellar = frame["catalogue_class"].map(_text).str.upper().eq("STAR")
    eligible = frame.loc[exact_identity & normalized & stellar].copy()
    if eligible.empty:
        eligible = frame.loc[exact_identity & normalized].copy()
    if eligible.empty:
        raise RuntimeError(
            "ConeSearch returned no exact-identity spectrum with a parameter extension"
        )
    g_sn = pd.to_numeric(eligible["catalogue_snrg"], errors="coerce").fillna(-1)
    i_sn = pd.to_numeric(eligible["catalogue_snri"], errors="coerce").fillna(-1)
    eligible["_selection_sn"] = pd.concat([g_sn, i_sn], axis=1).max(axis=1)
    eligible = eligible.sort_values("_selection_sn", ascending=False, kind="stable")
    return eligible.iloc[0], int(len(eligible))


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "1.2",
        "candidate_safe": True,
        "status": "failure",
        "transport": "anonymous_ivoa_conesearch_plus_public_gzip_fits",
        "release": "dr8/v2.0",
        "row_values_persisted": False,
        "selection_policy": (
            "Exact-digit Gaia DR3 identity, with_norm_flux=1, prefer STAR, then highest "
            "available max(g-band S/N, i-band S/N)."
        ),
        "claim_boundary": (
            "One arbitrary public parameter-bearing example is inspected in memory. "
            "No identifiers, coordinates, spectrum bytes, or radial-velocity values "
            "are persisted."
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

        sample, eligible_count = _select_parameter_sample(frame)
        payload["eligible_parameter_sample_count"] = eligible_count
        obsid = int(pd.to_numeric(sample["catalogue_obsid"], errors="raise"))
        body, fits_receipt = download_lamost_spectrum_fits(
            args.openapi_root,
            dr_version="dr8",
            sub_version="v2.0",
            obsid=obsid,
            timeout=args.timeout,
        )
        payload["fits_receipt"] = fits_receipt.to_record()
        extract_lasp_rv_from_fits(body)
        payload.update(
            {
                "status": "pass",
                "exact_gaia_dr3_identity_present": True,
                "parameter_extension_selected": True,
                "fits_has_finite_rv_and_positive_error": True,
            }
        )
        _write(args.output, payload)
    except Exception as error:
        if isinstance(error, LamostSpectrumFITSError) and error.receipt is not None:
            payload["fits_failure_receipt"] = error.receipt.to_record()
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:2000]
        _write(args.output, payload)
        raise


if __name__ == "__main__":
    main()
