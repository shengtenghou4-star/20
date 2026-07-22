#!/usr/bin/env python3
"""Discover the machine-readable LAMOST DR8 v1.0 access contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hou_compact.lamost_openapi import (
    DEFAULT_OPENAPI_ROOT,
    discover_openapi_contract,
)


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
    parser.add_argument(
        "--diagnostic-output",
        type=Path,
        default=None,
        help="write candidate-safe endpoint diagnostics even when validation fails",
    )
    return parser.parse_args()


def _safe_preview(text: str, maximum: int = 500) -> str:
    compact = " ".join(text.split())
    compact = re.sub(r"\b\d{15,20}\b", "<large-integer-redacted>", compact)
    return compact[:maximum]


def _probe_endpoint(url: str, *, timeout: float, maximum_bytes: int) -> dict[str, Any]:
    record: dict[str, Any] = {"url": url}
    request = Request(
        url,
        headers={
            "User-Agent": "HOU-COMPACT/0.1 LAMOST OpenAPI diagnostic",
            "Accept": "application/json,text/plain,*/*;q=0.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(maximum_bytes + 1)
            record["status"] = int(getattr(response, "status", 200))
            record["content_type"] = str(response.headers.get("Content-Type", ""))
        record["response_bytes"] = len(body)
        record["sha256"] = hashlib.sha256(body).hexdigest()
        record["oversized"] = len(body) > maximum_bytes
        bounded = body[:maximum_bytes]
        try:
            text = bounded.decode("utf-8-sig")
            record["utf8"] = True
            record["preview"] = _safe_preview(text)
            try:
                payload = json.loads(text)
                record["json"] = True
                record["payload_type"] = type(payload).__name__
                if isinstance(payload, dict):
                    record["top_level_keys"] = sorted(str(key) for key in payload)[:100]
                elif isinstance(payload, list):
                    record["top_level_length"] = len(payload)
                    if payload:
                        record["first_item_type"] = type(payload[0]).__name__
                        if isinstance(payload[0], dict):
                            record["first_item_keys"] = sorted(
                                str(key) for key in payload[0]
                            )[:100]
            except json.JSONDecodeError as error:
                record["json"] = False
                record["json_error"] = f"{error.msg} at char {error.pos}"
        except UnicodeDecodeError as error:
            record["utf8"] = False
            record["decode_error"] = str(error)
    except HTTPError as error:
        record.update(
            {
                "status": int(error.code),
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
        try:
            body = error.read(maximum_bytes)
            record["response_bytes"] = len(body)
            record["sha256"] = hashlib.sha256(body).hexdigest()
            record["preview"] = _safe_preview(body.decode("utf-8-sig", errors="replace"))
        except Exception:
            pass
    except (URLError, TimeoutError, OSError) as error:
        record.update(
            {
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    return record


def _write_diagnostic(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    args = parse_args()
    root = args.openapi_root.rstrip("/")
    version_root = f"{root}/{args.dr_version}/{args.sub_version}"
    endpoints = {
        "versions": f"{root}/dr_versions",
        "tables": f"{version_root}/tables",
        "tap": f"{version_root}/voservice/tap_url",
    }
    diagnostic: dict[str, Any] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "release": f"{args.dr_version}/{args.sub_version}",
        "endpoints": {
            name: _probe_endpoint(
                url,
                timeout=args.timeout,
                maximum_bytes=args.maximum_response_bytes,
            )
            for name, url in endpoints.items()
        },
        "claim_boundary": (
            "Diagnostics contain public metadata endpoint structure only. Large integer "
            "tokens are redacted; no catalogue source query is performed."
        ),
    }
    _write_diagnostic(args.diagnostic_output, diagnostic)
    try:
        result = discover_openapi_contract(
            openapi_root=args.openapi_root,
            dr_version=args.dr_version,
            sub_version=args.sub_version,
            timeout=args.timeout,
            retries=args.retries,
            maximum_response_bytes=args.maximum_response_bytes,
        )
    except Exception as error:
        diagnostic["validation"] = {
            "status": "failure",
            "error_type": type(error).__name__,
            "error": str(error),
        }
        _write_diagnostic(args.diagnostic_output, diagnostic)
        raise
    diagnostic["validation"] = {"status": "success"}
    _write_diagnostic(args.diagnostic_output, diagnostic)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
