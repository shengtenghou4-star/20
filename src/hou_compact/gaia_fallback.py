"""Fail-closed Gaia TAP provider fallback for the frozen HOU-COMPACT cohort.

The ESA archive remains authoritative and is always attempted first. Gaia@AIP is used
only for an explicit ESA anonymous-filesystem quota rejection or the equivalent generic
HTTP-400 ``DALServiceError`` currently emitted when ESA suppresses that rejection body.
Query text, ordering, row limit, output format, and all downstream scientific gates remain
unchanged. The mirror result is never accepted merely because the primary provider failed.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pyvo

from hou_compact.gaia import (
    DEFAULT_STATUS_PARSE_RETRIES,
    DEFAULT_STATUS_PARSE_RETRY_BACKOFF_SECONDS,
    _cached_job_phase,
    _prepare_query_paths,
    _wait_for_job_with_parse_retries,
    _write_success,
    failure_manifest_path,
    run_async_query,
    write_failure_manifest,
)
from hou_compact.http_timeout import (
    DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS,
    MinimumTimeoutSession,
    validate_minimum_http_timeout,
)

AIP_GAIA_TAP_URL = "https://gaia.aip.de/tap"
AIP_LONG_QUEUE = "2h"
_ALLOWED_AIP_QUEUES = frozenset({"30s", "5m", "2h"})
_QUOTA_TOKENS = (
    "filesystem quota exceeded",
    "anonymous",
    "allowed value",
)
_GENERIC_ESA_400_TOKENS = (
    "400 client error",
    "bad request",
)
_EXPLICIT_QUOTA_TRIGGER = "esa_anonymous_filesystem_quota"
_GENERIC_ESA_400_TRIGGER = "esa_dalservice_http_400"


def _failure_manifest_payload(output_path: Path) -> dict[str, object]:
    path = failure_manifest_path(output_path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _failure_manifest_message(output_path: Path) -> str:
    return str(_failure_manifest_payload(output_path).get("error_message", ""))


def _failure_manifest_error_type(output_path: Path) -> str:
    return str(_failure_manifest_payload(output_path).get("error_type", ""))


def classify_esa_fallback_failure(
    error: BaseException,
    output_path: Path,
) -> str | None:
    """Return the narrow provider-fallback trigger, or ``None`` to fail closed.

    ESA sometimes returns the full anonymous-filesystem quota message and sometimes
    collapses the same submission rejection to a generic HTTP-400 ``DALServiceError``.
    The latter is eligible only when both the exception/failure manifest identify the
    PyVO service-error type and the message has the exact 400/Bad Request shape. This does
    not catch local validation errors, arbitrary runtime failures, HTTP 5xx, timeouts, or
    malformed UWS responses.
    """
    manifest_message = _failure_manifest_message(output_path)
    message = " ".join((str(error), manifest_message)).lower()
    if all(token in message for token in _QUOTA_TOKENS):
        return _EXPLICIT_QUOTA_TRIGGER

    error_types = {
        type(error).__name__.strip().lower(),
        _failure_manifest_error_type(output_path).strip().lower(),
    }
    if (
        "dalserviceerror" in error_types
        and all(token in message for token in _GENERIC_ESA_400_TOKENS)
    ):
        return _GENERIC_ESA_400_TRIGGER
    return None


def is_esa_anonymous_quota_failure(error: BaseException, output_path: Path) -> bool:
    """Return true only for the explicit ESA anonymous-filesystem quota rejection."""
    return classify_esa_fallback_failure(error, output_path) == _EXPLICIT_QUOTA_TRIGGER


def _validate_aip_queue(queue: str) -> str:
    value = str(queue).strip()
    if value not in _ALLOWED_AIP_QUEUES:
        raise ValueError(f"unsupported Gaia@AIP queue: {value!r}")
    return value


def run_aip_async_query(
    query_path: Path,
    output_path: Path,
    *,
    overwrite: bool = False,
    maxrec: int | None = None,
    wait_timeout_seconds: float = 3600.0,
    fetch_retries: int = 3,
    delete_job: bool = True,
    minimum_http_timeout_seconds: float = DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS,
    status_parse_retries: int = DEFAULT_STATUS_PARSE_RETRIES,
    status_parse_retry_backoff_seconds: float = (
        DEFAULT_STATUS_PARSE_RETRY_BACKOFF_SECONDS
    ),
    queue: str = AIP_LONG_QUEUE,
    primary_error_type: str = "unknown",
    fallback_trigger: str = _EXPLICIT_QUOTA_TRIGGER,
) -> dict[str, object]:
    """Run the unchanged frozen query through Gaia@AIP's anonymous async queue."""
    query_path, output_path, query = _prepare_query_paths(
        query_path,
        output_path,
        overwrite=overwrite,
    )
    if maxrec is not None and maxrec < 1:
        raise ValueError("maxrec must be positive when provided")
    if not math.isfinite(wait_timeout_seconds) or wait_timeout_seconds <= 0:
        raise ValueError("wait_timeout_seconds must be finite and positive")
    if fetch_retries < 0:
        raise ValueError("fetch_retries must be non-negative")
    queue = _validate_aip_queue(queue)
    if fallback_trigger not in {
        _EXPLICIT_QUOTA_TRIGGER,
        _GENERIC_ESA_400_TRIGGER,
    }:
        raise ValueError(f"unsupported Gaia fallback trigger: {fallback_trigger!r}")
    minimum_http_timeout_seconds = validate_minimum_http_timeout(
        minimum_http_timeout_seconds
    )

    job = None
    tap_session = MinimumTimeoutSession(minimum_http_timeout_seconds)
    job_details: dict[str, object] = {
        "maxrec": maxrec,
        "wait_timeout_seconds": wait_timeout_seconds,
        "minimum_http_timeout_seconds": minimum_http_timeout_seconds,
        "fetch_retries": fetch_retries,
        "delete_job": delete_job,
        "service_provider": "Gaia@AIP",
        "async_queue": queue,
        "fallback_trigger": fallback_trigger,
        "primary_error_type": primary_error_type,
        "status_parse_retries_allowed": status_parse_retries,
        "status_parse_retry_backoff_seconds": status_parse_retry_backoff_seconds,
        "status_parse_failures": 0,
    }
    try:
        service = pyvo.dal.TAPService(AIP_GAIA_TAP_URL, session=tap_session)
        job = service.submit_job(query, maxrec=maxrec, queue=queue)
        job_details["job_url"] = str(job.url)
        job_details["job_id"] = str(job.job_id)
        job.run()
        _wait_for_job_with_parse_retries(
            job,
            timeout_seconds=wait_timeout_seconds,
            parse_retries=status_parse_retries,
            retry_backoff_seconds=status_parse_retry_backoff_seconds,
            details=job_details,
        )
        job_details["terminal_phase"] = _cached_job_phase(job)
        job.raise_if_error()
        result = job.fetch_result(max_retries=fetch_retries)
        table = result.to_table()
        manifest = _write_success(
            query_path,
            output_path,
            query,
            table,
            tap_url=AIP_GAIA_TAP_URL,
            execution_mode="async",
            overwrite=overwrite,
            details=job_details,
        )
    except Exception as fallback_error:
        if job is not None:
            try:
                job_details["terminal_phase"] = _cached_job_phase(job)
            except Exception:
                pass
        write_failure_manifest(
            query_path,
            output_path,
            tap_url=AIP_GAIA_TAP_URL,
            query=query,
            error=fallback_error,
            execution_mode="async",
            details=job_details,
        )
        raise
    finally:
        if job is not None and delete_job:
            try:
                job.delete()
            except Exception:
                pass
        tap_session.close()
    return manifest


def run_async_query_with_quota_fallback(
    query_path: Path,
    output_path: Path,
    *,
    overwrite: bool = False,
    maxrec: int | None = None,
    execution_duration_seconds: float | None = None,
    wait_timeout_seconds: float = 3600.0,
    fetch_retries: int = 3,
    delete_job: bool = True,
    minimum_http_timeout_seconds: float = DEFAULT_MINIMUM_HTTP_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run ESA first and use AIP only for a narrowly classified provider rejection."""
    try:
        return run_async_query(
            query_path,
            output_path,
            overwrite=overwrite,
            maxrec=maxrec,
            execution_duration_seconds=execution_duration_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            fetch_retries=fetch_retries,
            delete_job=delete_job,
            minimum_http_timeout_seconds=minimum_http_timeout_seconds,
        )
    except Exception as primary_error:
        fallback_trigger = classify_esa_fallback_failure(primary_error, output_path)
        if fallback_trigger is None:
            raise
        return run_aip_async_query(
            query_path,
            output_path,
            overwrite=True,
            maxrec=maxrec,
            wait_timeout_seconds=wait_timeout_seconds,
            fetch_retries=fetch_retries,
            delete_job=delete_job,
            minimum_http_timeout_seconds=minimum_http_timeout_seconds,
            queue=AIP_LONG_QUEUE,
            primary_error_type=type(primary_error).__name__,
            fallback_trigger=fallback_trigger,
        )
