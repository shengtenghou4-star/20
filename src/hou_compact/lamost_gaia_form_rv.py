"""Bounded one-to-many LAMOST form acquisition by exact Gaia DR2 source ID.

This client consumes the audited Gaia DR3-to-DR2 bridge, submits only accepted exact
DR2 identifiers to the first-party LAMOST DR8 search form, and validates every
returned Gaia identifier and spectrum obsid. A Gaia source may legitimately return
multiple spectra; an obsid may appear only once globally.

Source-level rows, bridge mappings and transport receipts are candidate-sensitive and
belong in encrypted private artifacts. The safe summary contains aggregate counts
only.
"""

from __future__ import annotations

import csv
import hashlib
import http.cookiejar
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from hou_compact.lamost_form_rv import (
    LamostFormError,
    ParsedTable,
    _multipart_body,
    _open_bounded,
    _parse_delimited,
    _safe_path,
    _same_origin_followups,
)
from hou_compact.lamost_form_rv_v2 import normalize_parsed_table

_EXACT_ID = re.compile(r"^[0-9]{10,20}$")
_EXACT_OBSID = re.compile(r"^[0-9]+$")
_ACCEPTED_BRIDGE_STATUS = "accepted_unique_or_separated_nearest"
_REQUIRED_RESPONSE_COLUMNS = {
    "gaia_source_id",
    "obsid",
    "lmjd",
    "rv",
    "rv_err",
    "fibermask",
}
_DEFAULT_OUTPUT_COLUMNS = (
    "gaia_source_id",
    "obsid",
    "lmjd",
    "mjd",
    "obsdate",
    "rv",
    "rv_err",
    "snrg",
    "snri",
    "class",
    "subclass",
    "fibermask",
)


class LamostGaiaFormError(LamostFormError):
    """Raised when the exact Gaia-ID form contract is violated."""


def _chunks(values: Sequence[str], size: int) -> Iterator[tuple[str, ...]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])


def _normalized_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise LamostGaiaFormError("bridge table has no header")
    mapping: dict[str, str] = {}
    for original in fieldnames:
        normalized = str(original).strip().lower().lstrip("\ufeff")
        if not normalized:
            raise LamostGaiaFormError("bridge table contains an empty header")
        if normalized in mapping:
            raise LamostGaiaFormError(f"duplicate normalized bridge header {normalized!r}")
        mapping[normalized] = str(original)
    return mapping


def _exact(value: object, pattern: re.Pattern[str], *, label: str) -> str:
    token = "" if value is None else str(value)
    if token != token.strip() or not pattern.fullmatch(token):
        raise LamostGaiaFormError(f"{label} is not exact integer text")
    return token


def load_accepted_bridge(path: Path) -> dict[str, str]:
    """Return exact DR2->DR3 mapping for accepted, one-to-one bridge rows."""

    if not path.exists() or path.stat().st_size == 0:
        raise LamostGaiaFormError("Gaia bridge input is missing or empty")
    mapping_by_dr2: dict[str, str] = {}
    seen_dr3: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        columns = _normalized_headers(reader.fieldnames)
        missing = sorted({"source_id", "dr2_source_id", "dr2_bridge_status"} - set(columns))
        if missing:
            raise LamostGaiaFormError(f"Gaia bridge is missing columns: {missing}")
        for row in reader:
            if None in row:
                raise LamostGaiaFormError("Gaia bridge row has extra fields")
            status = str(row.get(columns["dr2_bridge_status"], "")).strip()
            if status != _ACCEPTED_BRIDGE_STATUS:
                continue
            dr3 = _exact(row.get(columns["source_id"]), _EXACT_ID, label="DR3 source_id")
            dr2 = _exact(row.get(columns["dr2_source_id"]), _EXACT_ID, label="DR2 source_id")
            if dr3 in seen_dr3:
                raise LamostGaiaFormError("accepted bridge repeats a DR3 source_id")
            if dr2 in mapping_by_dr2:
                raise LamostGaiaFormError("accepted bridge repeats a DR2 source_id")
            seen_dr3.add(dr3)
            mapping_by_dr2[dr2] = dr3
    if not mapping_by_dr2:
        raise LamostGaiaFormError("Gaia bridge contains no accepted source mappings")
    return dict(sorted(mapping_by_dr2.items(), key=lambda item: (len(item[0]), item[0])))


def _parse_response(raw: bytes, *, source_kind: str, source_url: str) -> ParsedTable | None:
    return normalize_parsed_table(
        _parse_delimited(raw, source_kind=source_kind, source_url=source_url)
    )


def _fetch_batch(
    opener: Any,
    *,
    action_url: str,
    referer_url: str,
    dr2_ids: tuple[str, ...],
    output_columns: tuple[str, ...],
    collection: str,
    timeout: float,
    maximum_response_bytes: int,
) -> tuple[ParsedTable, list[dict[str, object]]]:
    boundary = "----HOUCOMPACT" + secrets.token_hex(16)
    fields: list[tuple[str, str]] = [
        ("sForm", "0"),
        ("pos.type", "none"),
        ("gaiasourcearea", "\n".join(dr2_ids)),
        ("output.collection", collection),
        ("output.fmt", "csv"),
    ]
    fields.extend((f"output.combined.{column}", "on") for column in output_columns)
    fields.append(("sBtn", "Search"))
    body = _multipart_body(fields, boundary)
    origin = f"{urlparse(action_url).scheme}://{urlparse(action_url).netloc}"
    request = Request(
        action_url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "HOU-COMPACT/0.8 exact Gaia DR2 LAMOST form client",
            "Accept": "text/csv,text/plain,text/html,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Origin": origin,
            "Referer": referer_url,
        },
        method="POST",
    )
    status, final_url, content_type, raw = _open_bounded(
        opener,
        request,
        timeout=timeout,
        maximum_bytes=maximum_response_bytes,
    )
    receipts: list[dict[str, object]] = [
        {
            "kind": "form_post",
            "http_status": status,
            "content_type": content_type,
            "response_bytes": len(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "final_url_path": _safe_path(final_url),
        }
    ]
    direct = _parse_response(raw, source_kind="form_post", source_url=final_url)
    if direct is not None:
        return direct, receipts
    for link in _same_origin_followups(raw, base_url=final_url):
        follow_request = Request(
            link,
            headers={
                "User-Agent": "HOU-COMPACT/0.8 exact Gaia DR2 LAMOST form client",
                "Accept": "text/csv,text/plain,*/*;q=0.1",
                "Accept-Encoding": "identity",
                "Referer": final_url,
            },
        )
        follow_status, follow_url, follow_type, follow_raw = _open_bounded(
            opener,
            follow_request,
            timeout=timeout,
            maximum_bytes=maximum_response_bytes,
        )
        receipts.append(
            {
                "kind": "same_origin_followup",
                "http_status": follow_status,
                "content_type": follow_type,
                "response_bytes": len(follow_raw),
                "response_sha256": hashlib.sha256(follow_raw).hexdigest(),
                "final_url_path": _safe_path(follow_url),
            }
        )
        parsed = _parse_response(
            follow_raw,
            source_kind="same_origin_followup",
            source_url=follow_url,
        )
        if parsed is not None:
            return parsed, receipts
    raise LamostGaiaFormError("LAMOST Gaia form exposed no bounded delimited result")


def _validate_batch(
    table: ParsedTable,
    *,
    requested_ids: set[str],
    expected_columns: tuple[str, ...] | None,
) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    missing = sorted(_REQUIRED_RESPONSE_COLUMNS - set(table.columns))
    if missing:
        raise LamostGaiaFormError(f"LAMOST Gaia response is missing columns: {missing}")
    if expected_columns is not None and table.columns != expected_columns:
        raise LamostGaiaFormError("LAMOST Gaia response header changed between batches")
    gaia_index = table.columns.index("gaia_source_id")
    obsid_index = table.columns.index("obsid")
    records: list[dict[str, str]] = []
    batch_obsids: set[str] = set()
    for row in table.rows:
        dr2 = _exact(row[gaia_index], _EXACT_ID, label="returned Gaia DR2 source_id")
        obsid = _exact(row[obsid_index], _EXACT_OBSID, label="returned obsid")
        if dr2 not in requested_ids:
            raise LamostGaiaFormError("LAMOST Gaia response contains an ID outside the batch")
        if obsid in batch_obsids:
            raise LamostGaiaFormError("LAMOST Gaia response repeats an obsid within one batch")
        batch_obsids.add(obsid)
        records.append(dict(zip(table.columns, row)))
    return records, table.columns


def acquire_gaia_form_rv(
    *,
    bridge_input: Path,
    rows_output: Path,
    overlap_output: Path,
    private_manifest_path: Path,
    safe_summary_path: Path,
    search_url: str = "https://www.lamost.org/dr8/v1.0/search",
    action_url: str = "https://www.lamost.org/dr8/v1.0/q",
    batch_size: int = 100,
    collection: str = "minimal",
    output_columns: tuple[str, ...] = _DEFAULT_OUTPUT_COLUMNS,
    timeout: float = 180.0,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    retries: int = 2,
    opener: Any | None = None,
    sleep: Any = time.sleep,
) -> dict[str, object]:
    """Acquire all spectra for exact accepted DR2 IDs and write private/safe receipts."""

    if not search_url.startswith("https://") or not action_url.startswith("https://"):
        raise ValueError("LAMOST URLs must use HTTPS")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if maximum_response_bytes < 1024:
        raise ValueError("maximum_response_bytes must be at least 1024")
    if retries < 1:
        raise ValueError("retries must be positive")

    bridge = load_accepted_bridge(bridge_input)
    dr2_ids = tuple(bridge)
    if opener is None:
        opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    search_request = Request(
        search_url,
        headers={
            "User-Agent": "HOU-COMPACT/0.8 exact Gaia DR2 LAMOST form client",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    search_status, search_final, search_type, search_raw = _open_bounded(
        opener,
        search_request,
        timeout=timeout,
        maximum_bytes=8 * 1024 * 1024,
    )

    private_manifest: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_sensitive": True,
        "status": "started",
        "accepted_bridge_sources": len(bridge),
        "batch_size": batch_size,
        "collection": collection,
        "output_columns": list(output_columns),
        "search_session": {
            "http_status": search_status,
            "content_type": search_type,
            "response_bytes": len(search_raw),
            "response_sha256": hashlib.sha256(search_raw).hexdigest(),
            "final_url_path": _safe_path(search_final),
        },
        "batches": [],
    }
    safe_summary: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "started",
        "accepted_bridge_sources": len(bridge),
        "batch_size": batch_size,
        "batch_count": 0,
        "returned_spectrum_rows": 0,
        "returned_unique_obsids": 0,
        "returned_unique_dr2_sources": 0,
        "returned_unique_dr3_sources": 0,
        "bridge_sources_without_spectra": len(bridge),
        "columns": None,
        "claim_boundary": (
            "Aggregate exact Gaia-DR2 acquisition only. No source ID, obsid, coordinate, "
            "RV value, spectrum row, candidate score or classification is disclosed."
        ),
    }

    def write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    rows_output.parent.mkdir(parents=True, exist_ok=True)
    overlap_output.parent.mkdir(parents=True, exist_ok=True)
    rows_temp = rows_output.with_suffix(rows_output.suffix + ".tmp")
    overlap_temp = overlap_output.with_suffix(overlap_output.suffix + ".tmp")
    expected_columns: tuple[str, ...] | None = None
    all_obsids: set[str] = set()
    returned_dr2: set[str] = set()
    returned_dr3: set[str] = set()
    rows_handle = None
    overlap_handle = None
    try:
        rows_handle = rows_temp.open("w", encoding="utf-8", newline="")
        overlap_handle = overlap_temp.open("w", encoding="utf-8", newline="")
        rows_writer: csv.DictWriter | None = None
        overlap_writer = csv.DictWriter(
            overlap_handle,
            fieldnames=[
                "obsid",
                "lmjd",
                "hou_compact_dr2_source_id",
                "hou_compact_dr3_source_id",
            ],
            extrasaction="raise",
        )
        overlap_writer.writeheader()

        for batch_index, batch in enumerate(_chunks(dr2_ids, batch_size), start=1):
            receipt: dict[str, object] = {
                "batch_index": batch_index,
                "requested_source_count": len(batch),
                "status": "failure",
                "attempts": [],
            }
            last_error: Exception | None = None
            for attempt in range(1, retries + 1):
                try:
                    table, transport = _fetch_batch(
                        opener,
                        action_url=action_url,
                        referer_url=search_final,
                        dr2_ids=batch,
                        output_columns=output_columns,
                        collection=collection,
                        timeout=timeout,
                        maximum_response_bytes=maximum_response_bytes,
                    )
                    records, columns = _validate_batch(
                        table,
                        requested_ids=set(batch),
                        expected_columns=expected_columns,
                    )
                    if expected_columns is None:
                        expected_columns = columns
                        rows_writer = csv.DictWriter(
                            rows_handle,
                            fieldnames=list(columns)
                            + [
                                "hou_compact_dr2_source_id",
                                "hou_compact_dr3_source_id",
                            ],
                            extrasaction="raise",
                        )
                        rows_writer.writeheader()
                    assert rows_writer is not None
                    batch_dr2: set[str] = set()
                    for record in records:
                        dr2 = record["gaia_source_id"]
                        obsid = record["obsid"]
                        if obsid in all_obsids:
                            raise LamostGaiaFormError(
                                "LAMOST Gaia response repeats an obsid across batches"
                            )
                        dr3 = bridge[dr2]
                        all_obsids.add(obsid)
                        batch_dr2.add(dr2)
                        returned_dr2.add(dr2)
                        returned_dr3.add(dr3)
                        augmented = {
                            **record,
                            "hou_compact_dr2_source_id": dr2,
                            "hou_compact_dr3_source_id": dr3,
                        }
                        rows_writer.writerow(augmented)
                        overlap_writer.writerow(
                            {
                                "obsid": obsid,
                                "lmjd": record["lmjd"],
                                "hou_compact_dr2_source_id": dr2,
                                "hou_compact_dr3_source_id": dr3,
                            }
                        )
                    receipt.update(
                        {
                            "status": "success",
                            "successful_attempt": attempt,
                            "returned_spectrum_rows": len(records),
                            "returned_source_count": len(batch_dr2),
                            "missing_source_count": len(batch) - len(batch_dr2),
                            "delimiter": table.delimiter,
                            "source_kind": table.source_kind,
                            "response_sha256": table.response_sha256,
                            "response_bytes": table.response_bytes,
                            "response_url_path": table.source_url_path,
                            "transport": transport,
                        }
                    )
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
                    receipt["attempts"].append(
                        {
                            "attempt": attempt,
                            "error_type": type(error).__name__,
                            "error": str(error)[:1000],
                        }
                    )
                    if attempt < retries:
                        sleep(min(10, attempt * 2))
            private_manifest["batches"].append(receipt)
            write_json(private_manifest_path, private_manifest)
            if last_error is not None:
                raise last_error

        rows_handle.flush()
        overlap_handle.flush()
        rows_handle.close()
        overlap_handle.close()
        rows_handle = None
        overlap_handle = None
        rows_temp.replace(rows_output)
        overlap_temp.replace(overlap_output)
        safe_summary.update(
            {
                "status": "success",
                "batch_count": len(private_manifest["batches"]),
                "returned_spectrum_rows": len(all_obsids),
                "returned_unique_obsids": len(all_obsids),
                "returned_unique_dr2_sources": len(returned_dr2),
                "returned_unique_dr3_sources": len(returned_dr3),
                "bridge_sources_without_spectra": len(bridge) - len(returned_dr2),
                "columns": list(expected_columns or ()),
            }
        )
        private_manifest.update(
            {
                "status": "success",
                "returned_spectrum_rows": len(all_obsids),
                "returned_unique_obsids": len(all_obsids),
                "returned_dr2_sources": sorted(returned_dr2, key=lambda value: (len(value), value)),
                "missing_dr2_sources": sorted(
                    set(bridge) - returned_dr2, key=lambda value: (len(value), value)
                ),
                "rows_output_sha256": hashlib.sha256(rows_output.read_bytes()).hexdigest(),
                "overlap_output_sha256": hashlib.sha256(overlap_output.read_bytes()).hexdigest(),
            }
        )
        write_json(private_manifest_path, private_manifest)
        write_json(safe_summary_path, safe_summary)
        return safe_summary
    except Exception as error:
        if rows_handle is not None:
            rows_handle.close()
        if overlap_handle is not None:
            overlap_handle.close()
        rows_temp.unlink(missing_ok=True)
        overlap_temp.unlink(missing_ok=True)
        rows_output.unlink(missing_ok=True)
        overlap_output.unlink(missing_ok=True)
        private_manifest.update(
            {
                "status": "failure",
                "error_type": type(error).__name__,
                "error": str(error)[:2000],
            }
        )
        safe_summary.update(
            {
                "status": "failure",
                "batch_count": len(private_manifest["batches"]),
                "returned_spectrum_rows": len(all_obsids),
                "returned_unique_obsids": len(all_obsids),
                "returned_unique_dr2_sources": len(returned_dr2),
                "returned_unique_dr3_sources": len(returned_dr3),
                "bridge_sources_without_spectra": len(bridge) - len(returned_dr2),
                "error_type": type(error).__name__,
                "error": str(error)[:1000],
            }
        )
        write_json(private_manifest_path, private_manifest)
        write_json(safe_summary_path, safe_summary)
        raise
