"""Multi-session orchestration for exact Gaia DR2 LAMOST form acquisition.

Live production showed that five consecutive successful form batches could be
followed by a non-tabular sixth response. This wrapper preserves the already audited
one-to-many client and limits each fresh cookie session to a bounded number of
batches. Session outputs are merged only after global exact-ID, header, and obsid
uniqueness checks.
"""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Iterator, Sequence

from hou_compact.lamost_gaia_form_rv import (
    _ACCEPTED_BRIDGE_STATUS,
    LamostGaiaFormError,
    acquire_gaia_form_rv,
    load_accepted_bridge,
)


def _chunks(values: Sequence[tuple[str, str]], size: int) -> Iterator[list[tuple[str, str]]]:
    if size < 1:
        raise ValueError("session source limit must be positive")
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        if not reader.fieldnames:
            raise LamostGaiaFormError(f"session output {path.name} has no header")
        rows = list(reader)
    if any(None in row for row in rows):
        raise LamostGaiaFormError(f"session output {path.name} has extra fields")
    return list(reader.fieldnames), rows


def acquire_gaia_form_rv_sessioned(
    *,
    bridge_input: Path,
    rows_output: Path,
    overlap_output: Path,
    private_manifest_path: Path,
    safe_summary_path: Path,
    batch_size: int = 100,
    batches_per_session: int = 5,
    collection: str = "minimal",
    timeout: float = 180.0,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    retries: int = 2,
) -> dict[str, object]:
    """Run the exact Gaia form client in fresh bounded cookie sessions."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if batches_per_session < 1:
        raise ValueError("batches_per_session must be positive")
    bridge = load_accepted_bridge(bridge_input)
    bridge_items = list(bridge.items())
    session_source_limit = batch_size * batches_per_session

    private: dict[str, Any] = {
        "schema_version": "0.2",
        "candidate_sensitive": True,
        "status": "started",
        "accepted_bridge_sources": len(bridge_items),
        "batch_size": batch_size,
        "batches_per_session": batches_per_session,
        "session_source_limit": session_source_limit,
        "sessions": [],
    }
    safe: dict[str, Any] = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "status": "started",
        "accepted_bridge_sources": len(bridge_items),
        "batch_size": batch_size,
        "batches_per_session": batches_per_session,
        "session_source_limit": session_source_limit,
        "session_count": 0,
        "returned_spectrum_rows": 0,
        "returned_unique_obsids": 0,
        "returned_unique_dr2_sources": 0,
        "returned_unique_dr3_sources": 0,
        "bridge_sources_without_spectra": len(bridge_items),
        "columns": None,
        "claim_boundary": (
            "Aggregate exact Gaia-DR2 acquisition only. No source ID, obsid, coordinate, "
            "RV value, spectrum row, candidate score or classification is disclosed."
        ),
    }

    def write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(path)

    rows_output.parent.mkdir(parents=True, exist_ok=True)
    overlap_output.parent.mkdir(parents=True, exist_ok=True)
    rows_temp = rows_output.with_suffix(rows_output.suffix + ".tmp")
    overlap_temp = overlap_output.with_suffix(overlap_output.suffix + ".tmp")
    rows_writer: csv.DictWriter | None = None
    overlap_writer: csv.DictWriter | None = None
    rows_handle = None
    overlap_handle = None
    expected_rows_header: list[str] | None = None
    expected_overlap_header: list[str] | None = None
    global_obsids: set[str] = set()
    returned_dr2: set[str] = set()
    returned_dr3: set[str] = set()

    try:
        rows_handle = rows_temp.open("w", encoding="utf-8", newline="")
        overlap_handle = overlap_temp.open("w", encoding="utf-8", newline="")
        with tempfile.TemporaryDirectory(prefix="hou-compact-gaia-form-") as root:
            root_path = Path(root)
            for session_index, group in enumerate(
                _chunks(bridge_items, session_source_limit), start=1
            ):
                session_dir = root_path / f"session_{session_index:03d}"
                session_dir.mkdir(parents=True)
                mini_bridge = session_dir / "bridge.csv"
                with mini_bridge.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=["source_id", "dr2_source_id", "dr2_bridge_status"],
                    )
                    writer.writeheader()
                    for dr2, dr3 in group:
                        writer.writerow(
                            {
                                "source_id": dr3,
                                "dr2_source_id": dr2,
                                "dr2_bridge_status": _ACCEPTED_BRIDGE_STATUS,
                            }
                        )

                session_rows = session_dir / "rows.csv"
                session_overlap = session_dir / "overlap.csv"
                session_private = session_dir / "private.json"
                session_safe = session_dir / "safe.json"
                session_summary = acquire_gaia_form_rv(
                    bridge_input=mini_bridge,
                    rows_output=session_rows,
                    overlap_output=session_overlap,
                    private_manifest_path=session_private,
                    safe_summary_path=session_safe,
                    batch_size=batch_size,
                    collection=collection,
                    timeout=timeout,
                    maximum_response_bytes=maximum_response_bytes,
                    retries=retries,
                )
                rows_header, rows = _read_rows(session_rows)
                overlap_header, overlaps = _read_rows(session_overlap)
                if expected_rows_header is None:
                    expected_rows_header = rows_header
                    rows_writer = csv.DictWriter(
                        rows_handle,
                        fieldnames=rows_header,
                        extrasaction="raise",
                    )
                    rows_writer.writeheader()
                elif rows_header != expected_rows_header:
                    raise LamostGaiaFormError("row header changed between fresh sessions")
                if expected_overlap_header is None:
                    expected_overlap_header = overlap_header
                    overlap_writer = csv.DictWriter(
                        overlap_handle,
                        fieldnames=overlap_header,
                        extrasaction="raise",
                    )
                    overlap_writer.writeheader()
                elif overlap_header != expected_overlap_header:
                    raise LamostGaiaFormError("overlap header changed between fresh sessions")
                assert rows_writer is not None and overlap_writer is not None

                session_obsids = {row["obsid"] for row in rows}
                overlap_obsids = {row["obsid"] for row in overlaps}
                if session_obsids != overlap_obsids:
                    raise LamostGaiaFormError(
                        "session rows and overlap disagree on exact obsid membership"
                    )
                duplicate = global_obsids.intersection(session_obsids)
                if duplicate:
                    raise LamostGaiaFormError("an obsid repeats across fresh sessions")
                global_obsids.update(session_obsids)
                for row in rows:
                    dr2 = row["hou_compact_dr2_source_id"]
                    dr3 = row["hou_compact_dr3_source_id"]
                    if bridge.get(dr2) != dr3:
                        raise LamostGaiaFormError(
                            "session row disagrees with the accepted DR2-to-DR3 bridge"
                        )
                    returned_dr2.add(dr2)
                    returned_dr3.add(dr3)
                    rows_writer.writerow(row)
                overlap_writer.writerows(overlaps)

                session_private_payload = json.loads(
                    session_private.read_text(encoding="utf-8")
                )
                private["sessions"].append(
                    {
                        "session_index": session_index,
                        "source_count": len(group),
                        "safe_summary": session_summary,
                        "private_manifest": session_private_payload,
                    }
                )
                safe["session_count"] = session_index
                safe["returned_spectrum_rows"] = len(global_obsids)
                safe["returned_unique_obsids"] = len(global_obsids)
                safe["returned_unique_dr2_sources"] = len(returned_dr2)
                safe["returned_unique_dr3_sources"] = len(returned_dr3)
                safe["bridge_sources_without_spectra"] = len(bridge) - len(returned_dr2)
                safe["columns"] = expected_rows_header
                write_json(private_manifest_path, private)
                write_json(safe_summary_path, safe)

        rows_handle.flush()
        overlap_handle.flush()
        rows_handle.close()
        overlap_handle.close()
        rows_handle = None
        overlap_handle = None
        rows_temp.replace(rows_output)
        overlap_temp.replace(overlap_output)
        safe["status"] = "success"
        private.update(
            {
                "status": "success",
                "returned_spectrum_rows": len(global_obsids),
                "returned_unique_obsids": len(global_obsids),
                "returned_dr2_sources": sorted(
                    returned_dr2, key=lambda value: (len(value), value)
                ),
                "missing_dr2_sources": sorted(
                    set(bridge) - returned_dr2, key=lambda value: (len(value), value)
                ),
                "rows_output_sha256": hashlib.sha256(rows_output.read_bytes()).hexdigest(),
                "overlap_output_sha256": hashlib.sha256(
                    overlap_output.read_bytes()
                ).hexdigest(),
            }
        )
        write_json(private_manifest_path, private)
        write_json(safe_summary_path, safe)
        return safe
    except Exception as error:
        if rows_handle is not None:
            rows_handle.close()
        if overlap_handle is not None:
            overlap_handle.close()
        rows_temp.unlink(missing_ok=True)
        overlap_temp.unlink(missing_ok=True)
        rows_output.unlink(missing_ok=True)
        overlap_output.unlink(missing_ok=True)
        private.update(
            {
                "status": "failure",
                "error_type": type(error).__name__,
                "error": str(error)[:2000],
            }
        )
        safe.update(
            {
                "status": "failure",
                "error_type": type(error).__name__,
                "error": str(error)[:1000],
            }
        )
        write_json(private_manifest_path, private)
        write_json(safe_summary_path, safe)
        raise
