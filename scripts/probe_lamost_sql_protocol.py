#!/usr/bin/env python3
"""Probe the public LAMOST SQL protocol with a constant SELECT 1 query."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hou_compact.lamost_openapi import DEFAULT_OPENAPI_ROOT
from hou_compact.lamost_sql import probe_public_sql_protocol


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default=DEFAULT_OPENAPI_ROOT)
    parser.add_argument("--dr-version", default="dr8")
    parser.add_argument("--sub-version", default="v1.0")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--maximum-response-bytes",
        type=int,
        default=16 * 1024 * 1024,
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def _write(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    args = parse_args()
    diagnostic: dict[str, Any] = {
        "status": "started",
        "release": f"{args.dr_version}/{args.sub_version}",
        "probe_query": "SELECT 1 AS hou_compact_probe",
        "claim_boundary": (
            "The probe query contains no catalogue table, source identifier, "
            "coordinate, spectrum, or candidate information."
        ),
    }
    _write(args.output, diagnostic)
    try:
        result = probe_public_sql_protocol(
            openapi_root=args.openapi_root,
            dr_version=args.dr_version,
            sub_version=args.sub_version,
            timeout=args.timeout,
            retries=args.retries,
            maximum_response_bytes=args.maximum_response_bytes,
        )
    except Exception as error:
        diagnostic["status"] = "failure"
        diagnostic["error_type"] = type(error).__name__
        diagnostic["error"] = str(error)[:4000]
        _write(args.output, diagnostic)
        raise
    _write(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
