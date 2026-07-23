"""Bounded POST transport for the first-party LAMOST table-query endpoint.

The official ``pylamost`` client submits a JSON ``TableQuery`` body to
``/openapi/<dr>/<sub>/query/<table>``.  This module preserves that contract while
adding response-size limits and candidate-safe receipts.  Request bodies, source
identifiers, positions, and returned row values are never included in receipts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


class LamostTableQueryError(RuntimeError):
    """Raised when a LAMOST table-query response cannot satisfy the contract."""

    def __init__(
        self,
        message: str,
        *,
        receipt: TableQueryReceipt | None = None,
    ) -> None:
        super().__init__(message)
        self.receipt = receipt


@dataclass(frozen=True)
class TableQueryReceipt:
    endpoint: str
    table_name: str
    status: int
    attempts: int
    request_bytes: int
    request_sha256: str
    response_bytes: int
    response_sha256: str
    content_type: str
    response_kind: str
    row_count: int
    returned_columns: tuple[str, ...] = ()
    top_level_keys: tuple[str, ...] = ()
    diagnostic_error_code: str | None = None
    diagnostic_error_description: str | None = None

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        return {key: value for key, value in record.items() if value is not None}


def _sanitize(value: object, *, limit: int = 500) -> str:
    text = " ".join(str(value).split())
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    text = re.sub(r"\b\d{6,}\b", "[number-redacted]", text)
    return text[:limit]


def _error_details(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    lowered = {str(key).lower(): value for key, value in payload.items()}
    code = lowered.get("error", lowered.get("code", lowered.get("status")))
    description = lowered.get(
        "description",
        lowered.get("message", lowered.get("detail")),
    )
    return (
        _sanitize(code, limit=160) if code is not None else None,
        _sanitize(description) if description is not None else None,
    )


def _is_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    lowered = {str(key).lower(): value for key, value in payload.items()}
    if any(key in lowered for key in ("error", "errors", "exception")):
        return True
    status = str(lowered.get("status", "")).strip().lower()
    return status in {"error", "failed", "failure"} or lowered.get("success") is False


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
    columns_value = lowered.get("columns")
    columns: list[str] | None = None
    if isinstance(columns_value, list) and all(
        isinstance(value, str) for value in columns_value
    ):
        columns = [str(value) for value in columns_value]
    for key in ("data", "rows", "records", "results", "result", "items"):
        value = lowered.get(key)
        if isinstance(value, list):
            if not value:
                return pd.DataFrame(columns=columns or [])
            if all(isinstance(row, dict) for row in value):
                return pd.DataFrame(value)
            if columns is not None and all(
                isinstance(row, (list, tuple)) for row in value
            ):
                return pd.DataFrame(value, columns=columns)
        if isinstance(value, dict):
            nested = _rows_from_payload(value)
            if nested is not None:
                return nested
    return None


def _receipt(
    *,
    endpoint: str,
    table_name: str,
    status: int,
    attempts: int,
    request_body: bytes,
    response_body: bytes,
    content_type: str,
    response_kind: str,
    frame: pd.DataFrame | None = None,
    payload: Any = None,
) -> TableQueryReceipt:
    code, description = _error_details(payload)
    return TableQueryReceipt(
        endpoint=endpoint,
        table_name=table_name,
        status=status,
        attempts=attempts,
        request_bytes=len(request_body),
        request_sha256=hashlib.sha256(request_body).hexdigest(),
        response_bytes=len(response_body),
        response_sha256=hashlib.sha256(response_body).hexdigest(),
        content_type=content_type,
        response_kind=response_kind,
        row_count=0 if frame is None else int(len(frame)),
        returned_columns=(
            ()
            if frame is None
            else tuple(sorted(str(column).lower() for column in frame.columns))
        ),
        top_level_keys=(
            tuple(sorted(str(key) for key in payload)[:50])
            if isinstance(payload, dict)
            else ()
        ),
        diagnostic_error_code=code,
        diagnostic_error_description=description,
    )


def post_table_query(
    openapi_root: str,
    *,
    dr_version: str,
    sub_version: str,
    table_name: str,
    query: Mapping[str, Any],
    token: str | None = None,
    timeout: float = 180.0,
    retries: int = 2,
    maximum_request_bytes: int = 256 * 1024,
    maximum_response_bytes: int = 32 * 1024 * 1024,
    opener: Any = urlopen,
) -> tuple[pd.DataFrame, TableQueryReceipt]:
    """Submit one bounded TableQuery request and return tabular rows."""

    root = openapi_root.rstrip("/")
    if not root.startswith("https://"):
        raise ValueError("openapi_root must use HTTPS")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name) is None:
        raise ValueError("unsafe table_name")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    endpoint = f"{root}/{dr_version}/{sub_version}/query/{table_name}"
    suffix = urlencode({"token": token}) if token is not None else ""
    request_url = endpoint if not suffix else f"{endpoint}?{suffix}"
    request_body = json.dumps(
        dict(query),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(request_body) > maximum_request_bytes:
        raise ValueError("TableQuery request exceeded the byte limit")
    request = Request(
        request_url,
        data=request_body,
        method="POST",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 bounded LAMOST TableQuery client",
            "Accept": "application/json,*/*;q=0.1",
            "Content-Type": "application/json",
        },
    )
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                content_type = str(response.headers.get("Content-Type", ""))
                response_body = response.read(maximum_response_bytes + 1)
            if len(response_body) > maximum_response_bytes:
                raise LamostTableQueryError("TableQuery response exceeded the byte limit")
            preview = response_body[:8192].lstrip().lower()
            if preview.startswith(b"<!doctype html") or b"<html" in preview:
                receipt = _receipt(
                    endpoint=endpoint,
                    table_name=table_name,
                    status=status,
                    attempts=attempt + 1,
                    request_body=request_body,
                    response_body=response_body,
                    content_type=content_type,
                    response_kind="html",
                )
                raise LamostTableQueryError(
                    "TableQuery returned HTML instead of JSON",
                    receipt=receipt,
                )
            try:
                payload = json.loads(response_body.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                receipt = _receipt(
                    endpoint=endpoint,
                    table_name=table_name,
                    status=status,
                    attempts=attempt + 1,
                    request_body=request_body,
                    response_body=response_body,
                    content_type=content_type,
                    response_kind="invalid_json",
                )
                raise LamostTableQueryError(
                    "TableQuery returned invalid JSON",
                    receipt=receipt,
                ) from error
            frame = _rows_from_payload(payload)
            response_kind = (
                "json_list" if isinstance(payload, list) else "json_object"
            )
            receipt = _receipt(
                endpoint=endpoint,
                table_name=table_name,
                status=status,
                attempts=attempt + 1,
                request_body=request_body,
                response_body=response_body,
                content_type=content_type,
                response_kind=response_kind,
                frame=frame,
                payload=payload,
            )
            if status != 200:
                raise LamostTableQueryError(
                    f"TableQuery returned HTTP {status}",
                    receipt=receipt,
                )
            if _is_error(payload):
                detail = ": ".join(
                    value
                    for value in (
                        receipt.diagnostic_error_code,
                        receipt.diagnostic_error_description,
                    )
                    if value
                )
                message = "TableQuery returned an error envelope"
                if detail:
                    message = f"{message}: {detail}"
                raise LamostTableQueryError(message, receipt=receipt)
            if frame is None:
                raise LamostTableQueryError(
                    "TableQuery JSON contained no recognizable tabular rows",
                    receipt=receipt,
                )
            frame.columns = [str(column).lower() for column in frame.columns]
            return frame.reset_index(drop=True), receipt
        except HTTPError as error:
            last_error = error
            response_body = error.read(maximum_response_bytes + 1)
            receipt = _receipt(
                endpoint=endpoint,
                table_name=table_name,
                status=int(error.code),
                attempts=attempt + 1,
                request_body=request_body,
                response_body=response_body[:maximum_response_bytes],
                content_type=str(error.headers.get("Content-Type", "")),
                response_kind="http_error",
            )
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise LamostTableQueryError(
                    f"TableQuery returned HTTP {error.code}",
                    receipt=receipt,
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise LamostTableQueryError(
                    f"TableQuery transport failed: {type(error).__name__}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise LamostTableQueryError(str(last_error))
