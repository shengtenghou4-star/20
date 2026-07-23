#!/usr/bin/env python3
"""Validate the anonymous LAMOST DR8 v2.0 ConeSearch RV contract.

The official example cone is used only to inspect the returned column contract in
memory. No coordinates, source identifiers, radial velocities, or row values are
persisted. Position is accepted only as row discovery; downstream identity still
requires exact returned Gaia DR3 character equality.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from hou_compact.lamost_conesearch import query_lamost_cone
from hou_compact.lamost_dr3_spectra import DR3SpectrumSpec
from hou_compact.lamost_openapi import discover_openapi_contract

_CLAIM_BOUNDARY = (
    "One arbitrary public cone is inspected in memory only. No row values, source "
    "identifiers, coordinates, spectra, or radial velocities are persisted. Position "
    "is discovery only; exact returned Gaia DR3 character equality remains mandatory."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument(
        "--conesearch-endpoint",
        default="https://www.lamost.org/dr8/v2.0/voservice/conesearch",
    )
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v2.0")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_conesearch_contract.json"),
    )
    return parser.parse_args()


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    print(text)


def _identity_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii").strip()
    return str(value).strip()


def main() -> None:
    args = parse_args()
    spec = DR3SpectrumSpec()
    payload: dict[str, object] = {
        "schema_version": "0.9",
        "candidate_safe": True,
        "status": "failure",
        "release": f"{args.dr_version}/{args.sub_version}",
        "openapi_root": args.openapi_root,
        "conesearch_endpoint": args.conesearch_endpoint,
        "transport": "bounded_anonymous_ivoa_conesearch",
        "diagnostic_scope": "official_example_cone_values_discarded",
        "frozen_table_contract": spec.to_record(),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    try:
        contract = discover_openapi_contract(
            openapi_root=args.openapi_root,
            dr_version=args.dr_version,
            sub_version=args.sub_version,
            timeout=args.timeout,
        )
        payload["openapi_status"] = contract.get("status")
        payload["openapi_receipts"] = contract.get("receipts", {})
        payload["openapi_tables_status"] = contract.get("openapi_tables_status")

        frame, receipt = query_lamost_cone(
            args.conesearch_endpoint,
            ra_deg=10.0004738,
            dec_deg=40.9952444,
            radius_deg=0.01,
            timeout=args.timeout,
        )
        returned = {str(column).lower() for column in frame.columns}
        required = {column.lower() for column in spec.selected_columns}
        missing = sorted(required - returned)
        payload.update(
            {
                "probe_row_count": int(len(frame)),
                "returned_columns": sorted(returned),
                "missing_required_columns": missing,
                "source_row_values_persisted": False,
                "conesearch_receipt": receipt.to_record(),
            }
        )
        if missing:
            raise RuntimeError(f"ConeSearch contract missing columns: {missing}")
        if frame.empty:
            raise RuntimeError("official example cone returned no rows")

        identity_column = spec.gaia_source_id_column.lower()
        exact_identity_rows = 0
        for value in frame[identity_column]:
            text = _identity_text(value)
            if re.fullmatch(r"[0-9]+", text):
                exact_identity_rows += 1
        if exact_identity_rows < 1:
            raise RuntimeError(
                "ConeSearch returned no Gaia DR3 identifiers serialized as exact digits"
            )

        payload.update(
            {
                "status": "pass",
                "required_columns_present": True,
                "exact_gaia_dr3_character_rows_ge_1": True,
            }
        )
        _write(args.output, payload)
    except Exception as error:
        payload["status"] = "failure"
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:2_000]
        _write(args.output, payload)
        raise


if __name__ == "__main__":
    main()
