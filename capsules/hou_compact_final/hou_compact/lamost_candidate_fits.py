#!/usr/bin/env python3
"""Download exact first-party gzip FITS for candidate obsids without logging identities."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from astropy.io import fits

_EXACT_OBSID = re.compile(r"^[0-9]+$")
_MAX_WIRE_BYTES = 64 * 1024 * 1024
_MAX_DECODED_BYTES = 64 * 1024 * 1024


class CandidateFitsError(RuntimeError):
    pass


def _headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise CandidateFitsError("table has no header")
    result: dict[str, str] = {}
    for name in fieldnames:
        key = str(name).strip().lower().lstrip("\ufeff")
        if not key or key in result:
            raise CandidateFitsError("table has empty or duplicate normalized header")
        result[key] = str(name)
    return result


def load_obsids(path: Path) -> list[str]:
    obsids: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        mapping = _headers(reader.fieldnames)
        if "obsid" not in mapping:
            raise CandidateFitsError("candidate overlap lacks obsid")
        for row in reader:
            token = str(row.get(mapping["obsid"], ""))
            if token != token.strip() or not _EXACT_OBSID.fullmatch(token):
                raise CandidateFitsError("candidate overlap contains unsafe obsid")
            if token in seen:
                raise CandidateFitsError("candidate overlap repeats obsid")
            seen.add(token)
            obsids.append(token)
    if not obsids:
        raise CandidateFitsError("candidate overlap contains no obsids")
    return sorted(obsids, key=int)


def _read_bounded(response, maximum: int) -> bytes:
    output = bytearray()
    while True:
        chunk = response.read(min(1024 * 1024, maximum + 1 - len(output)))
        if not chunk:
            break
        output.extend(chunk)
        if len(output) > maximum:
            raise CandidateFitsError("FITS response exceeds bounded wire-size contract")
    return bytes(output)


def _decode(raw: bytes) -> tuple[bytes, str, str]:
    wire_sha = hashlib.sha256(raw).hexdigest()
    if raw.startswith(b"SIMPLE  ="):
        return raw, "identity", wire_sha
    if not raw.startswith(b"\x1f\x8b"):
        raise CandidateFitsError("first-party response is neither FITS nor gzip FITS")
    output = bytearray()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as compressed:
            while True:
                chunk = compressed.read(
                    min(1024 * 1024, _MAX_DECODED_BYTES + 1 - len(output))
                )
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > _MAX_DECODED_BYTES:
                    raise CandidateFitsError("decoded FITS exceeds bounded-size contract")
    except (gzip.BadGzipFile, EOFError, OSError) as error:
        raise CandidateFitsError(
            f"gzip FITS integrity failed: {type(error).__name__}"
        ) from error
    decoded = bytes(output)
    if not decoded.startswith(b"SIMPLE  ="):
        raise CandidateFitsError("decoded payload lacks FITS magic")
    return decoded, "gzip", wire_sha


def fetch_one(obsid: str, *, timeout: float, retries: int) -> tuple[bytes, dict[str, object]]:
    opener = build_opener()
    url = "https://www.lamost.org/openapi/dr8/v1.0/lrs/spectrum/fits?" + urlencode(
        {"obsid": obsid}
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = Request(
            url,
            headers={
                "User-Agent": "HOU-COMPACT/1.5 encrypted final hybrid capsule",
                "Accept": "application/fits,application/gzip,application/octet-stream,*/*;q=0.1",
                "Accept-Encoding": "identity",
            },
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise CandidateFitsError("first-party FITS endpoint did not return 200")
                raw = _read_bounded(response, _MAX_WIRE_BYTES)
            decoded, encoding, wire_sha = _decode(raw)
            with fits.open(
                io.BytesIO(decoded),
                mode="readonly",
                memmap=False,
                do_not_scale_image_data=True,
                ignore_missing_end=False,
            ) as hdul:
                header_obsid = str(hdul[0].header.get("OBSID", "")).strip()
                date_obs = str(hdul[0].header.get("DATE-OBS", "")).strip()
                if header_obsid != obsid:
                    raise CandidateFitsError("FITS header OBSID mismatch")
                if "T" not in date_obs or len(date_obs) < 19:
                    raise CandidateFitsError("FITS DATE-OBS lacks full UTC timestamp")
            return decoded, {
                "encoding": encoding,
                "wire_sha256": wire_sha,
                "decoded_sha256": hashlib.sha256(decoded).hexdigest(),
                "wire_bytes": len(raw),
                "decoded_bytes": len(decoded),
                "gzip_crc_read_to_eof": encoding == "gzip",
                "attempt": attempt,
            }
        except (HTTPError, URLError, TimeoutError, OSError, CandidateFitsError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(attempt * 2)
    assert last_error is not None
    raise CandidateFitsError(
        f"first-party FITS acquisition failed after retries: {type(last_error).__name__}"
    ) from last_error


def acquire(
    *,
    overlap_path: Path,
    output_dir: Path,
    manifest_path: Path,
    private_receipt_path: Path,
    safe_summary_path: Path,
    timeout: float = 180.0,
    retries: int = 3,
) -> dict[str, object]:
    obsids = load_obsids(overlap_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    receipts: list[dict[str, object]] = []
    encoding_counts: dict[str, int] = {}
    for index, obsid in enumerate(obsids, start=1):
        decoded, receipt = fetch_one(obsid, timeout=timeout, retries=retries)
        path = output_dir / f"spectrum_{index:03d}.fits"
        path.write_bytes(decoded)
        rows.append({"obsid": obsid, "fits_path": str(path)})
        receipts.append({"obsid": obsid, **receipt})
        encoding = str(receipt["encoding"])
        encoding_counts[encoding] = encoding_counts.get(encoding, 0) + 1
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["obsid", "fits_path"])
        writer.writeheader()
        writer.writerows(rows)
    private_receipt = {
        "schema_version": "1.0",
        "candidate_sensitive": True,
        "status": "success",
        "expected_obsids": len(obsids),
        "downloaded_obsids": len(rows),
        "spectra": receipts,
    }
    private_receipt_path.write_text(
        json.dumps(private_receipt, indent=2, sort_keys=True), encoding="utf-8"
    )
    safe = {
        "schema_version": "1.0",
        "candidate_safe": True,
        "expected_obsids": len(obsids),
        "downloaded_obsids": len(rows),
        "exact_header_obsid_matches": len(rows),
        "full_date_obs_headers": len(rows),
        "encoding_counts": dict(sorted(encoding_counts.items())),
        "all_gzip_crc_read_to_eof": all(
            bool(item.get("gzip_crc_read_to_eof"))
            or item.get("encoding") == "identity"
            for item in receipts
        ),
        "claim_boundary": "Exact FITS identity and timing acquisition only.",
    }
    safe_summary_path.write_text(
        json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8"
    )
    return safe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("overlap", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--private-receipt", type=Path, required=True)
    parser.add_argument("--safe-summary", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()
    result = acquire(
        overlap_path=args.overlap,
        output_dir=args.output_dir,
        manifest_path=args.manifest,
        private_receipt_path=args.private_receipt,
        safe_summary_path=args.safe_summary,
        timeout=args.timeout,
        retries=args.retries,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
