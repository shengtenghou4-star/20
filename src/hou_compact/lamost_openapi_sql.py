"""Bounded SQL transport for the first-party public LAMOST OpenAPI.

LAMOST's supported Python client submits SQL with an HTTPS GET request to the
release-scoped ``/openapi/<dr>/<sub>/sql`` endpoint. This module exposes a tiny
``run_sync`` adapter used by the Dark-668 table-discovery and exact-ID query
helpers. Receipts never retain SQL text, query parameters, or source IDs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


class LamostOpenAPISQLError(RuntimeError):
    """Raised when a bounded LAMOST OpenAPI SQL request cannot be validated."""

    def __init__(
        self,
        message: str,
        *,
        receipts: list[OpenAPISQLReceipt] | None = None,
    ) -> None:
        super().__init__(message)
        self.receipts = list(receipts or [])


@dataclass(frozen=True)
class OpenAPISQLReceipt:
    """Candidate-safe provenance for one OpenAPI SQL HTTP request."""

    endpoint: str
    request_kind: str
    status: int
    attempts: int
    response_bytes: int
    content_type: str
    sha256: str
    query_sha256: str
    maxrec: int
    response_kind: str
    top_level_keys: tuple[str, ...] = ()
    diagnostic_error_code: str | None = None
    diagnostic_error_description: str | None = None

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        return {key: value for key, value in record.items() if value is not None}


def _top_level_keys(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()
    return tuple(sorted(str(key) for key in payload)[:50])


def _response_kind(payload: Any) -> str:
    if isinstance(payload, list):
        return "json_list"
    if isinstance(payload, dict):
        return "json_object"
    return f"json_{type(payload).__name__.lower()}"


def _api_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    lowered = {str(key).lower(): value for key, value in payload.items()}
    if any(key in lowered for key in ("error", "errors", "exception")):
        return True
    status = str(lowered.get("status", "")).strip().lower()
    success = lowered.get("success")
    return status in {"error", "failed", "failure"} or success is False


def _sanitize_diagnostic_text(value: object, *, limit: int = 500) -> str:
    """Bound and redact metadata-only API diagnostics before persistence."""

    text = " ".join(str(value).split())
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    text = re.sub(r"\b\d{12,}\b", "[long-number-redacted]", text)
    text = re.sub(
        r"(?is)\bselect\b.+",
        "[sql-redacted]",
        text,
        count=1,
    )
    return text[:limit]


def _diagnostic_error_details(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    lowered = {str(key).lower(): value for key, value in payload.items()}
    code_value = lowered.get("error", lowered.get("code", lowered.get("status")))
    description_value = lowered.get(
        "description",
        lowered.get("message", lowered.get("detail")),
    )
    code = (
        _sanitize_diagnostic_text(code_value, limit=160)
        if code_value is not None
        else None
    )
    description = (
        _sanitize_diagnostic_text(description_value)
        if description_value is not None
        else None
    )
    return code or None, description or None


def _extract_sqlid(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in {"sqlid", "sql_id", "query_id"}:
                text = str(value).strip()
                if text:
                    return text
        for value in payload.values():
            found = _extract_sqlid(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _extract_sqlid(value)
            if found is not None:
                return found
    return None


def _extract_count(payload: Any) -> int | None:
    if isinstance(payload, bool):
        return None
    if isinstance(payload, int):
        return payload if payload >= 0 else None
    if isinstance(payload, str) and payload.strip().isdigit():
        return int(payload.strip())
    if isinstance(payload, dict):
        for key in ("count", "total", "rows", "row_count", "result_count"):
            for actual, value in payload.items():
                if str(actual).lower() == key:
                    found = _extract_count(value)
                    if found is not None:
                        return found
        for value in payload.values():
            found = _extract_count(value)
            if found is not None:
                return found
    return None


def _column_names(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("name", item.get("column_name"))
            if name is None:
                return None
            names.append(str(name))
        else:
            return None
    return names


def _rows_from_payload(payload: Any) -> pd.DataFrame | None:
    if isinstance(payload, list):
        if not payload:
            return pd.DataFrame()
        if all(isinstance(row, dict) for row in payload):
            return pd.DataFrame(payload)
        return None
    if not isinstance(payload, dict):
        return None

    lowered = {str(key).lower(): value for key, value in payload.items()}
    columns = _column_names(lowered.get("columns"))
    for data_key in ("data", "rows", "records", "items", "results", "result"):
        value = lowered.get(data_key)
        if isinstance(value, list):
            if not value:
                return pd.DataFrame(columns=columns or [])
            if all(isinstance(row, dict) for row in value):
                return pd.DataFrame(value)
            if columns is not None and all(isinstance(row, (list, tuple)) for row in value):
                return pd.DataFrame(value, columns=columns)
        if isinstance(value, dict):
            nested = _rows_from_payload(value)
            if nested is not None:
                return nested

    for value in payload.values():
        nested = _rows_from_payload(value)
        if nested is not None:
            return nested

    envelope_keys = {
        "status",
        "success",
        "message",
        "description",
        "sqlid",
        "sql_id",
        "query_id",
        "count",
        "total",
    }
    if payload and not envelope_keys.intersection(lowered):
        if all(not isinstance(value, (dict, list, tuple)) for value in payload.values()):
            return pd.DataFrame([payload])
    return None


def _rewrite_for_openapi_sql(query: str, maxrec: int) -> str:
    statement = query.strip().rstrip(";")
    if not statement:
        raise ValueError("query must not be empty")

    top_match = re.match(r"(?is)^\s*SELECT\s+TOP\s+(\d+)\s+", statement)
    explicit_top: int | None = None
    if top_match is not None:
        explicit_top = int(top_match.group(1))
        statement = re.sub(
            r"(?is)^\s*SELECT\s+TOP\s+\d+\s+",
            "SELECT ",
            statement,
            count=1,
        )

    if re.search(r"(?i)\bTAP_SCHEMA\.columns\b", statement):
        statement = re.sub(
            r"(?i)\bTAP_SCHEMA\.columns\b",
            "information_schema.columns",
            statement,
        )
        statement = re.sub(
            r"(?i)\bdatatype\b",
            "data_type AS datatype",
            statement,
            count=1,
        )
        if re.search(r"(?i)\bWHERE\b", statement):
            statement = re.sub(
                r"(?i)\bWHERE\b",
                "WHERE table_schema = 'public' AND ",
                statement,
                count=1,
            )
        else:
            statement += " WHERE table_schema = 'public'"

    requested_limit = min(explicit_top or maxrec + 1, maxrec + 1)
    if not re.search(r"(?i)\bLIMIT\s+\d+\s*$", statement):
        statement += f" LIMIT {requested_limit}"
    return statement


def _request_json(
    endpoint: str,
    params: dict[str, object],
    *,
    request_kind: str,
    query_sha256: str,
    maxrec: int,
    timeout: float,
    retries: int,
    maximum_response_bytes: int,
    maximum_url_characters: int,
    diagnostic_error_details: bool,
    opener: Any,
) -> tuple[Any, OpenAPISQLReceipt]:
    encoded = urlencode({key: value for key, value in params.items() if value is not None})
    request_url = f"{endpoint}?{encoded}"
    if len(request_url) > maximum_url_characters:
        raise LamostOpenAPISQLError(
            "encoded LAMOST OpenAPI SQL request exceeds the URL-length limit"
        )
    request = Request(
        request_url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded LAMOST OpenAPI SQL client",
            "Accept": "application/json,*/*;q=0.1",
        },
    )
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("Content-Type", ""))
                body = response.read(maximum_response_bytes + 1)
            if len(body) > maximum_response_bytes:
                raise LamostOpenAPISQLError(
                    "LAMOST OpenAPI SQL response exceeded the byte limit"
                )
            preview = body[:8_192].lstrip().lower()
            if preview.startswith(b"<!doctype html") or b"<html" in preview:
                receipt = OpenAPISQLReceipt(
                    endpoint=endpoint,
                    request_kind=request_kind,
                    status=status,
                    attempts=attempt + 1,
                    response_bytes=len(body),
                    content_type=content_type,
                    sha256=hashlib.sha256(body).hexdigest(),
                    query_sha256=query_sha256,
                    maxrec=maxrec,
                    response_kind="html",
                )
                raise LamostOpenAPISQLError(
                    "LAMOST OpenAPI SQL returned HTML instead of JSON",
                    receipts=[receipt],
                )
            try:
                payload = json.loads(body.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                receipt = OpenAPISQLReceipt(
                    endpoint=endpoint,
                    request_kind=request_kind,
                    status=status,
                    attempts=attempt + 1,
                    response_bytes=len(body),
                    content_type=content_type,
                    sha256=hashlib.sha256(body).hexdigest(),
                    query_sha256=query_sha256,
                    maxrec=maxrec,
                    response_kind="invalid_json",
                )
                raise LamostOpenAPISQLError(
                    "LAMOST OpenAPI SQL response was not valid UTF-8 JSON",
                    receipts=[receipt],
                ) from error
            diagnostic_code: str | None = None
            diagnostic_description: str | None = None
            if diagnostic_error_details and _api_error(payload):
                diagnostic_code, diagnostic_description = _diagnostic_error_details(payload)
            receipt = OpenAPISQLReceipt(
                endpoint=endpoint,
                request_kind=request_kind,
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                content_type=content_type,
                sha256=hashlib.sha256(body).hexdigest(),
                query_sha256=query_sha256,
                maxrec=maxrec,
                response_kind=_response_kind(payload),
                top_level_keys=_top_level_keys(payload),
                diagnostic_error_code=diagnostic_code,
                diagnostic_error_description=diagnostic_description,
            )
            if status != 200:
                raise LamostOpenAPISQLError(
                    f"LAMOST OpenAPI SQL returned HTTP {status}",
                    receipts=[receipt],
                )
            if _api_error(payload):
                message = "LAMOST OpenAPI SQL returned an error envelope"
                if diagnostic_error_details:
                    detail = ": ".join(
                        value
                        for value in (diagnostic_code, diagnostic_description)
                        if value
                    )
                    if detail:
                        message = f"{message}: {detail}"
                raise LamostOpenAPISQLError(message, receipts=[receipt])
            return payload, receipt
        except HTTPError as error:
            last_error = error
            body = error.read(maximum_response_bytes + 1)
            receipt = OpenAPISQLReceipt(
                endpoint=endpoint,
                request_kind=request_kind,
                status=int(error.code),
                attempts=attempt + 1,
                response_bytes=min(len(body), maximum_response_bytes),
                content_type=str(error.headers.get("Content-Type", "")),
                sha256=hashlib.sha256(body[:maximum_response_bytes]).hexdigest(),
                query_sha256=query_sha256,
                maxrec=maxrec,
                response_kind="http_error",
            )
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise LamostOpenAPISQLError(
                    f"LAMOST OpenAPI SQL returned HTTP {error.code}",
                    receipts=[receipt],
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise LamostOpenAPISQLError(
                    f"LAMOST OpenAPI SQL transport failed: {type(error).__name__}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise LamostOpenAPISQLError(str(last_error))


def execute_openapi_sql(
    openapi_root: str,
    dr_version: str,
    sub_version: str,
    query: str,
    *,
    maxrec: int,
    token: str | None = None,
    timeout: float = 180.0,
    retries: int = 2,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    maximum_url_characters: int = 16_000,
    diagnostic_error_details: bool = False,
    opener: Any = urlopen,
) -> tuple[pd.DataFrame, list[OpenAPISQLReceipt]]:
    """Execute a bounded public LAMOST SQL request and return candidate-safe receipts."""

    root = openapi_root.rstrip("/")
    if not root.startswith("https://"):
        raise ValueError("openapi_root must use HTTPS")
    if maxrec < 1:
        raise ValueError("maxrec must be positive")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 1_024:
        raise ValueError("maximum_response_bytes must be at least 1024")
    if maximum_url_characters < 1_024:
        raise ValueError("maximum_url_characters must be at least 1024")

    statement = _rewrite_for_openapi_sql(query, maxrec)
    query_sha256 = hashlib.sha256(statement.encode("utf-8")).hexdigest()
    release_root = f"{root}/{dr_version}/{sub_version}"
    sql_endpoint = f"{release_root}/sql"
    receipts: list[OpenAPISQLReceipt] = []
    try:
        payload, receipt = _request_json(
            sql_endpoint,
            {"sql": statement, "output.fmt": "json", "token": token},
            request_kind="sql",
            query_sha256=query_sha256,
            maxrec=maxrec,
            timeout=timeout,
            retries=retries,
            maximum_response_bytes=maximum_response_bytes,
            maximum_url_characters=maximum_url_characters,
            diagnostic_error_details=diagnostic_error_details,
            opener=opener,
        )
        receipts.append(receipt)
        frame = _rows_from_payload(payload)
        if frame is None:
            sqlid = _extract_sqlid(payload)
            if sqlid is None:
                raise LamostOpenAPISQLError(
                    "LAMOST OpenAPI SQL JSON contained neither rows nor a query id",
                    receipts=receipts,
                )
            count_payload, count_receipt = _request_json(
                f"{release_root}/get_query_result_count",
                {"sqlid": sqlid, "token": token},
                request_kind="result_count",
                query_sha256=query_sha256,
                maxrec=maxrec,
                timeout=timeout,
                retries=retries,
                maximum_response_bytes=maximum_response_bytes,
                maximum_url_characters=maximum_url_characters,
                diagnostic_error_details=diagnostic_error_details,
                opener=opener,
            )
            receipts.append(count_receipt)
            count = _extract_count(count_payload)
            if count is None:
                raise LamostOpenAPISQLError(
                    "LAMOST OpenAPI SQL result count was not recognizable",
                    receipts=receipts,
                )
            rows_to_fetch = min(count, maxrec + 1)
            result_payload, result_receipt = _request_json(
                f"{release_root}/get_query_result",
                {
                    "sqlid": sqlid,
                    "rows": rows_to_fetch,
                    "page": 1,
                    "output.fmt": "json",
                    "token": token,
                },
                request_kind="result_page",
                query_sha256=query_sha256,
                maxrec=maxrec,
                timeout=timeout,
                retries=retries,
                maximum_response_bytes=maximum_response_bytes,
                maximum_url_characters=maximum_url_characters,
                diagnostic_error_details=diagnostic_error_details,
                opener=opener,
            )
            receipts.append(result_receipt)
            frame = _rows_from_payload(result_payload)
            if frame is None:
                raise LamostOpenAPISQLError(
                    "LAMOST OpenAPI SQL result page did not contain tabular rows",
                    receipts=receipts,
                )
        frame.columns = [str(column).lower() for column in frame.columns]
        if len(frame) > maxrec:
            raise LamostOpenAPISQLError(
                "LAMOST OpenAPI SQL result exceeded the configured maxrec",
                receipts=receipts,
            )
        return frame.reset_index(drop=True), receipts
    except LamostOpenAPISQLError as error:
        merged = [*receipts, *error.receipts]
        raise LamostOpenAPISQLError(str(error), receipts=merged) from error


class OpenAPISQLService:
    """Small ``run_sync`` adapter for existing Dark-668 exact-query helpers."""

    def __init__(
        self,
        openapi_root: str,
        *,
        dr_version: str = "dr8",
        sub_version: str = "v1.0",
        token: str | None = None,
        timeout: float = 180.0,
        retries: int = 2,
        maximum_response_bytes: int = 32 * 1024 * 1024,
        maximum_url_characters: int = 16_000,
        diagnostic_error_details: bool = False,
        opener: Any = urlopen,
    ) -> None:
        self.openapi_root = openapi_root
        self.dr_version = dr_version
        self.sub_version = sub_version
        self.token = token
        self.timeout = timeout
        self.retries = retries
        self.maximum_response_bytes = maximum_response_bytes
        self.maximum_url_characters = maximum_url_characters
        self.diagnostic_error_details = diagnostic_error_details
        self.opener = opener
        self.receipts: list[OpenAPISQLReceipt] = []

    @property
    def endpoint(self) -> str:
        root = self.openapi_root.rstrip("/")
        return f"{root}/{self.dr_version}/{self.sub_version}/sql"

    def run_sync(self, query: str, *, maxrec: int) -> pd.DataFrame:
        try:
            frame, receipts = execute_openapi_sql(
                self.openapi_root,
                self.dr_version,
                self.sub_version,
                query,
                maxrec=maxrec,
                token=self.token,
                timeout=self.timeout,
                retries=self.retries,
                maximum_response_bytes=self.maximum_response_bytes,
                maximum_url_characters=self.maximum_url_characters,
                diagnostic_error_details=self.diagnostic_error_details,
                opener=self.opener,
            )
        except LamostOpenAPISQLError as error:
            self.receipts.extend(error.receipts)
            raise
        self.receipts.extend(receipts)
        return frame
