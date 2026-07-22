#!/usr/bin/env python3
"""Validate the LAMOST TAP schema required by the Dark-668 live route.

Only TAP_SCHEMA metadata is queried. The probe validates both the per-spectrum
``obsid + rv + rv_err`` contract and an identity-safe multiple-epoch table whose Gaia
identifier is stored as integer or text. It never requests catalogue source rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hou_compact.lamost_openapi import discover_openapi_contract
from hou_compact.lamost_tap_get import TapGetService
from hou_compact.lamost_tap_mec import discover_mec_table_specs
from hou_compact.lamost_tap_rv import discover_rv_table_specs

_CLAIM_BOUNDARY = (
    "TAP_SCHEMA metadata only. No catalogue rows, source identifiers, coordinates, "
    "spectra, radial velocities, or candidate classifications were requested."
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
        "schema_version": "0.4",
        "candidate_safe": True,
        "status": "failure",
        "release": f"{args.dr_version}/{args.sub_version}",
        "openapi_root": args.openapi_root,
        "transport": "bounded_https_get",
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    service: TapGetService | None = None
    try:
        contract = discover_openapi_contract(
            openapi_root=args.openapi_root,
            dr_version=args.dr_version,
            sub_version=args.sub_version,
            timeout=args.timeout,
        )
        tap_urls = [str(value) for value in contract.get("tap_urls", [])]
        payload["openapi_status"] = contract.get("status")
        payload["openapi_receipts"] = contract.get("receipts", {})
        payload["tap_urls"] = tap_urls
        if not tap_urls:
            raise RuntimeError("LAMOST OpenAPI returned no TAP URL")

        tap_url = tap_urls[0]
        payload["tap_url"] = tap_url
        service = TapGetService(tap_url, timeout=args.timeout)
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

        payload["transport_receipts"] = [
            receipt.to_record() for receipt in service.receipts
        ]
        payload["contract_errors"] = contract_errors
        if contract_errors:
            payload["status"] = "contract_failure"
            _write(args.output, payload)
            failed = ", ".join(sorted(contract_errors))
            raise RuntimeError(f"LAMOST TAP schema contract failed: {failed}")
        payload["status"] = "pass"
        _write(args.output, payload)
    except Exception as error:
        if service is not None:
            payload["transport_receipts"] = [
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
