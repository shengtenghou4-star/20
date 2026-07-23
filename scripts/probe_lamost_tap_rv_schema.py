#!/usr/bin/env python3
"""Validate the direct Gaia DR3 LAMOST DR8 v2.0 RV contract.

The probe requests one arbitrary public AFGK spectrum from the documented
``stellar`` table.  It verifies the exact-character Gaia DR3 identifier and the
per-spectrum time/RV/error/quality fields.  No returned row values are persisted.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from hou_compact.lamost_dr3_spectra import DR3SpectrumSpec
from hou_compact.lamost_openapi import discover_openapi_contract
from hou_compact.lamost_openapi_sql import OpenAPISQLService

_CLAIM_BOUNDARY = (
    "One arbitrary public contract row is inspected in memory only. No row values, "
    "source identifiers, coordinates, spectra, or radial velocities are persisted."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v2.0")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_tap_rv_schema.json"),
    )
    return parser.parse_args()


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    print(text)


def main() -> None:
    args = parse_args()
    spec = DR3SpectrumSpec()
    payload: dict[str, object] = {
        "schema_version": "0.7",
        "candidate_safe": True,
        "status": "failure",
        "release": f"{args.dr_version}/{args.sub_version}",
        "openapi_root": args.openapi_root,
        "transport": "bounded_openapi_sql_get",
        "diagnostic_scope": "single_arbitrary_public_contract_row_values_discarded",
        "frozen_table_contract": spec.to_record(),
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    service: OpenAPISQLService | None = None
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

        service = OpenAPISQLService(
            args.openapi_root,
            dr_version=args.dr_version,
            sub_version=args.sub_version,
            timeout=args.timeout,
            diagnostic_error_details=True,
        )
        payload["sql_endpoint"] = service.endpoint
        columns = ", ".join(spec.selected_columns)
        query = (
            f"SELECT TOP 1 {columns} FROM {spec.table_name} "
            f"WHERE {spec.gaia_source_id_column} IS NOT NULL"
        )
        frame = service.run_sync(query, maxrec=1)
        lowered = {str(column).lower(): str(column) for column in frame.columns}
        missing = sorted(
            column for column in spec.selected_columns if column.lower() not in lowered
        )
        if missing:
            raise RuntimeError(f"stellar contract missing columns: {missing}")
        if len(frame) != 1:
            raise RuntimeError(
                f"stellar contract probe expected one row and received {len(frame)}"
            )
        raw_identity = frame.iloc[0][lowered[spec.gaia_source_id_column.lower()]]
        identity_text = str(raw_identity).strip()
        if not isinstance(raw_identity, str):
            raise RuntimeError(
                "gaia_source_id was not serialized as character data by OpenAPI"
            )
        if re.fullmatch(r"[0-9]+", identity_text) is None:
            raise RuntimeError("gaia_source_id character value was not exact integer text")

        payload.update(
            {
                "status": "pass",
                "probe_row_count": 1,
                "returned_columns": sorted(lowered),
                "gaia_source_id_serialization": "character_digits",
                "source_row_values_persisted": False,
                "sql_receipts": [
                    receipt.to_record() for receipt in service.receipts
                ],
            }
        )
        _write(args.output, payload)
    except Exception as error:
        if service is not None:
            payload["sql_receipts"] = [
                receipt.to_record() for receipt in service.receipts
            ]
        payload["status"] = "failure"
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:2_000]
        _write(args.output, payload)
        raise


if __name__ == "__main__":
    main()
