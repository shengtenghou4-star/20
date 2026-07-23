"""Gaia TAP acquisition with immutable success and failure manifests."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pyvo

from hou_compact.http_timeout import (
    DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS,
    MinimumTimeoutSession,
    validate_minimum_http_timeout,
)

DEFAULT_GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def success_manifest_path(output_path: Path) -> Path:
    """Return the immutable success-manifest path for a query output."""
    return output_path.with_suffix(output_path.suffix + ".manifest.json")


def failure_manifest_path(output_path: Path) -> Path:
    """Return the immutable failure-manifest path for a query attempt."""
    return output_path.with_suffix(output_path.suffix + ".failure.manifest.json")


def _query_provenance(
    query_path: Path,
    output_path: Path,
    *,
    tap_url: str,
    query: str,
    execution_mode: str,
) -> dict[str, object]:
    return {
        "created_utc": datetime.now(UTC).isoformat(),
        "tap_url": tap_url,
        "query_path": str(query_path),
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "output_path": str(output_path),
        "execution_mode": execution_mode,
    }


def write_failure_manifest(
    query_path: Path,
    output_path: Path,
    *,
    tap_url: str,
    query: str,
    error: BaseException,
    execution_mode: str = "sync",
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    """Persist a candidate-safe query-failure receipt and return its payload."""
    manifest = {
        **_query_provenance(
            query_path,
            output_path,
            tap_url=tap_url,
            query=query,
            execution_mode=execution_mode,
        ),
        "status": "failure",
        "error_type": type(error).__name__,
        "error_message": str(error)[:4000],
        "output_exists": output_path.exists(),
        **(details or {}),
    }
    path = failure_manifest_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _prepare_query_paths(
    query_path: Path,
    output_path: Path,
    *,
    overwrite: bool,
) -> tuple[Path, Path, str]:
    query_path = query_path.resolve()
    output_path = output_path.resolve()
    if not query_path.is_file():
        raise FileNotFoundError(query_path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {output_path}")
    query = query_path.read_text(encoding="utf-8")
    if not query.strip():
        raise ValueError("ADQL query is empty")
    return query_path, output_path, query


def _write_success(
    query_path: Path,
    output_path: Path,
    query: str,
    table: object,
    *,
    tap_url: str,
    execution_mode: str,
    overwrite: bool,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table.write(output_path, overwrite=overwrite)
    manifest: dict[str, object] = {
        **_query_provenance(
            query_path,
            output_path,
            tap_url=tap_url,
            query=query,
            execution_mode=execution_mode,
        ),
        "status": "success",
        "output_sha256": sha256_file(output_path),
        "row_count": len(table),
        "column_names": list(table.colnames),
        **(details or {}),
    }
    success_manifest_path(output_path).write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    failure_manifest_path(output_path).unlink(missing_ok=True)
    return manifest


def run_sync_query(
    query_path: Path,
    output_path: Path,
    *,
    tap_url: str = DEFAULT_GAIA_TAP_URL,
    overwrite: bool = False,
    maxrec: int | None = None,
) -> dict[str, object]:
    """Execute a short frozen ADQL query through the synchronous TAP endpoint."""
    query_path, output_path, query = _prepare_query_paths(
        query_path,
        output_path,
        overwrite=overwrite,
    )
    if maxrec is not None and maxrec < 1:
        raise ValueError("maxrec must be positive when provided")
    try:
        service = pyvo.dal.TAPService(tap_url)
        if maxrec is None:
            # ``search`` is the long-standing alias and is retained for clients/mocks that
            # predate the explicit ``run_sync`` method.
            result = service.search(query)
        else:
            result = service.run_sync(query, maxrec=maxrec)
        table = result.to_table()
    except Exception as error:
        write_failure_manifest(
            query_path,
            output_path,
            tap_url=tap_url,
            query=query,
            error=error,
            execution_mode="sync",
            details={"maxrec": maxrec},
        )
        raise
    return _write_success(
        query_path,
        output_path,
        query,
        table,
        tap_url=tap_url,
        execution_mode="sync",
        overwrite=overwrite,
        details={"maxrec": maxrec},
    )


def _cached_job_phase(job: object) -> str | None:
    """Return the phase already fetched by ``wait`` without another network request."""
    cached = getattr(job, "_job", None)
    phase = getattr(cached, "phase", None)
    if phase is not None:
        return str(phase)
    # Synthetic jobs and alternative clients may expose a local phase attribute directly.
    direct = getattr(job, "phase", None)
    return None if direct is None else str(direct)


def run_async_query(
    query_path: Path,
    output_path: Path,
    *,
    tap_url: str = DEFAULT_GAIA_TAP_URL,
    overwrite: bool = False,
    maxrec: int | None = None,
    execution_duration_seconds: float | None = None,
    wait_timeout_seconds: float = 3600.0,
    fetch_retries: int = 3,
    delete_job: bool = True,
    minimum_http_timeout_seconds: float = DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Execute a frozen ADQL query as a persistent server-side UWS job.

    Gaia's synchronous endpoint may abort expensive joins or ordered queries before the
    server has time to finish. The asynchronous path submits a UWS job, records its URL and
    phase, waits for a terminal state, fetches the result, and optionally removes the remote
    job after the local checksummed table is written.

    PyVO's UWS status requests may otherwise use a fixed ten-second read timeout. A
    dedicated TAP session raises only undersized HTTP timeouts to
    ``minimum_http_timeout_seconds``; the scientific wait deadline and query are unchanged.
    """
    query_path, output_path, query = _prepare_query_paths(
        query_path,
        output_path,
        overwrite=overwrite,
    )
    if maxrec is not None and maxrec < 1:
        raise ValueError("maxrec must be positive when provided")
    if execution_duration_seconds is not None and (
        not math.isfinite(execution_duration_seconds)
        or execution_duration_seconds <= 0
    ):
        raise ValueError("execution_duration_seconds must be finite and positive")
    if not math.isfinite(wait_timeout_seconds) or wait_timeout_seconds <= 0:
        raise ValueError("wait_timeout_seconds must be finite and positive")
    if fetch_retries < 0:
        raise ValueError("fetch_retries must be non-negative")
    minimum_http_timeout_seconds = validate_minimum_http_timeout(
        minimum_http_timeout_seconds
    )

    job = None
    tap_session = MinimumTimeoutSession(minimum_http_timeout_seconds)
    job_details: dict[str, object] = {
        "maxrec": maxrec,
        "requested_execution_duration_seconds": execution_duration_seconds,
        "wait_timeout_seconds": wait_timeout_seconds,
        "minimum_http_timeout_seconds": minimum_http_timeout_seconds,
        "fetch_retries": fetch_retries,
        "delete_job": delete_job,
    }
    try:
        service = pyvo.dal.TAPService(tap_url, session=tap_session)
        job = service.submit_job(query, maxrec=maxrec)
        job_details["job_url"] = str(job.url)
        job_details["job_id"] = str(job.job_id)
        if execution_duration_seconds is not None:
            try:
                job.execution_duration = execution_duration_seconds
                job_details["execution_duration_configured"] = True
            except Exception as configuration_error:
                job_details["execution_duration_configured"] = False
                job_details["execution_duration_configuration_error"] = (
                    f"{type(configuration_error).__name__}: {configuration_error}"
                )[:1000]
        else:
            job_details["execution_duration_configured"] = False
            job_details["execution_duration_configuration_skipped"] = True
        job.run().wait(timeout=wait_timeout_seconds)
        job_details["terminal_phase"] = _cached_job_phase(job)
        job.raise_if_error()
        result = job.fetch_result(max_retries=fetch_retries)
        table = result.to_table()
        manifest = _write_success(
            query_path,
            output_path,
            query,
            table,
            tap_url=tap_url,
            execution_mode="async",
            overwrite=overwrite,
            details=job_details,
        )
    except Exception as error:
        if job is not None:
            try:
                job_details["terminal_phase"] = _cached_job_phase(job)
            except Exception:
                pass
        write_failure_manifest(
            query_path,
            output_path,
            tap_url=tap_url,
            query=query,
            error=error,
            execution_mode="async",
            details=job_details,
        )
        raise
    finally:
        if job is not None and delete_job:
            try:
                job.delete()
            except Exception:
                # The local result/failure manifest is authoritative. Remote cleanup failure
                # must not invalidate an otherwise complete acquisition product.
                pass
        tap_session.close()
    return manifest
