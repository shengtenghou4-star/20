#!/usr/bin/env python3
"""Validate the LAMOST SQL schema required by the Dark-668 live route.

Only public ``information_schema.columns`` metadata is queried through the
release-scoped OpenAPI SQL endpoint. The probe validates both the per-spectrum
``obsid + rv + rv_err`` contract and an identity-safe multiple-epoch table whose
Gaia identifier is stored as integer or text. It never requests catalogue rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.lamost_openapi import discover_openapi_contract
from hou_compact.lamost_openapi_sql import OpenAPISQLService
from hou_compact.lamost_tap_mec import discover_mec_table_specs
from hou_compact.lamost_tap_rv import discover_rv_table_specs

_CLAIM_BOUNDARY = (
    "Public information-schema metadata only. No catalogue rows, source identifiers, "
    "coordinates, spectra, radial velocities, or candidate classifications were requested."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v1.0")
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
    payload: dict[str, object] = {
        "schema_version": "0.6",
        "candidate_safe": True,
        "status": "failure",
        "release": f"{args.dr_version}/{args.sub_version}",
        "openapi_root": args.openapi_root,
        "transport": "bounded_openapi_sql_get",
        "diagnostic_scope": "metadata_only_sanitized_error_details",
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
        contract_errors: dict[str, dict[str, str]] = {}

        try:
            rv_specs = discover_rv_table_specs(service)
            payload["rv_scoring_table_count"] = len(rv_specs)
            payload["rv_table_specs"] = [spec.to_record() for spec in rv_specs]
        except Exception as error:
            contract_errors["per_spectrum_rv"] = {
                "error_type": type(error).__name__,
                "error": str(error)[:2_000],
            }

        try:
            mec_specs = discover_mec_table_specs(service)
            payload["identity_safe_mec_table_count"] = len(mec_specs)
            payload["mec_table_specs"] = [spec.to_record() for spec in mec_specs]
        except Exception as error:
            contract_errors["multiple_epoch_identity"] = {
                "error_type": type(error).__name__,
                "error": str(error)[:2_000],
            }

        payload["sql_receipts"] = [receipt.to_record() for receipt in service.receipts]
        payload["contract_errors"] = contract_errors
        if contract_errors:
            payload["status"] = "contract_failure"
            _write(args.output, payload)
            failed = ", ".join(sorted(contract_errors))
            raise RuntimeError(f"LAMOST OpenAPI SQL schema contract failed: {failed}")
        payload["status"] = "pass"
        _write(args.output, payload)
    except Exception as error:
        if service is not None:
            payload["sql_receipts"] = [
                receipt.to_record() for receipt in service.receipts
            ]
        if payload.get("status") != "contract_failure":
            payload["status"] = "failure"
            payload["error_type"] = type(error).__name__
            payload["error"] = str(error)[:2_000]
            _write(args.output, payload)
        raise


if __name__ == "__main__":
    main()
