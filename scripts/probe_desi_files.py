#!/usr/bin/env python3
"""Probe a DESI file plan without downloading bulk survey data."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from hou_compact.gaia import sha256_file

USER_AGENT = "HOU-COMPACT/0.1 (public astronomy research; metadata probe)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="CSV produced by plan_desi_files.py")
    parser.add_argument("--output", type=Path, default=Path("outputs/desi_probe.csv"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-rows", type=int)
    return parser.parse_args()


def _probe_once(url: str, timeout: float) -> dict[str, object]:
    request = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return {
                "http_status": int(response.status),
                "exists": 200 <= response.status < 300,
                "content_length": response.headers.get("Content-Length"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "error": "",
            }
    except HTTPError as error:
        if error.code == 405:
            fallback = Request(
                url,
                method="GET",
                headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"},
            )
            with urlopen(fallback, timeout=timeout) as response:
                return {
                    "http_status": int(response.status),
                    "exists": response.status in {200, 206},
                    "content_length": response.headers.get("Content-Range")
                    or response.headers.get("Content-Length"),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "error": "",
                }
        return {
            "http_status": int(error.code),
            "exists": False,
            "content_length": None,
            "etag": None,
            "last_modified": None,
            "error": str(error.reason),
        }


def probe_url(url: str, timeout: float, retries: int) -> dict[str, object]:
    """Probe one URL with bounded retry for network failures and 5xx responses."""
    last: dict[str, object] | None = None
    for attempt in range(retries + 1):
        try:
            result = _probe_once(url, timeout)
        except (URLError, TimeoutError, OSError) as error:
            result = {
                "http_status": None,
                "exists": False,
                "content_length": None,
                "etag": None,
                "last_modified": None,
                "error": f"{type(error).__name__}: {error}",
            }
        last = result
        status = result["http_status"]
        retryable = status is None or (isinstance(status, int) and status >= 500)
        if not retryable or attempt == retries:
            return result
        time.sleep(0.5 * 2**attempt)
    assert last is not None
    return last


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("workers must be positive")
    if args.timeout <= 0:
        raise ValueError("timeout must be positive")
    if args.retries < 0:
        raise ValueError("retries must be non-negative")

    frame = pd.read_csv(args.input)
    if "url" not in frame.columns:
        raise KeyError("input plan has no url column")
    if args.max_rows is not None:
        frame = frame.head(args.max_rows).copy()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(
            executor.map(
                lambda url: probe_url(str(url), args.timeout, args.retries),
                frame["url"],
            )
        )

    probe = pd.DataFrame(results)
    output = pd.concat([frame.reset_index(drop=True), probe], axis=1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)

    status_counts = {
        str(key): int(value)
        for key, value in output["http_status"].fillna("network_error").value_counts().items()
    }
    manifest = {
        "input": str(args.input),
        "input_sha256": sha256_file(args.input),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "probed_rows": len(output),
        "existing_files": int(output["exists"].sum()),
        "unique_existing_healpix": int(output.loc[output["exists"], "healpix"].nunique()),
        "status_counts": status_counts,
        "workers": args.workers,
        "timeout_seconds": args.timeout,
        "retries": args.retries,
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
