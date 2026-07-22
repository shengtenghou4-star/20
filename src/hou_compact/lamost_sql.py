"""Bounded access to the official LAMOST OpenAPI SQL workflow."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class LAMOSTSQLError(RuntimeError):
    """Raised when the LAMOST SQL workflow violates its public contract."""


@dataclass(frozen=True)
class SQLReceipt:
    url_without_query: str
    status: int
    attempts: int
    response_bytes: int
    sha256: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _fetch_json_get(
    url: str,
    *,
    params: dict[str, object],
    timeout: float = 60.0,
    retries: int = 2,
    maximum_response_bytes: int = 16 * 1024 * 1024,
    opener: Any = urlopen,
) -> tuple[Any, SQLReceipt]:
    if not url.startswith("https://"):
        raise ValueError("LAMOST SQL URLs must use HTTPS")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 1024:
        raise ValueError("maximum_response_bytes must be at least 1024")

    query = urlencode(
        {key: value for key, value in params.items() if value is not None},
        doseq=True,
    )
    request = Request(
        f"{url}?{query}",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 LAMOST SQL client",
            "Accept": "application/json,*/*;q=0.1",
        },
    )
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                body = response.read(maximum_response_bytes + 1)
            if status != 200:
                raise LAMOSTSQLError(f"LAMOST SQL endpoint returned HTTP {status}")
            if len(body) > maximum_response_bytes:
                raise LAMOSTSQLError("LAMOST SQL response exceeded the byte limit")
            try:
                payload = json.loads(body.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise LAMOSTSQLError(
                    "LAMOST SQL response was not valid UTF-8 JSON"
                ) from error
            receipt = SQLReceipt(
                url_without_query=url,
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
            )
            return payload, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise LAMOSTSQLError(
                    f"LAMOST SQL endpoint returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise LAMOSTSQLError(
                    "LAMOST SQL transport error: "
                    f"{type(error).__name__}: {error}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise LAMOSTSQLError(str(last_error))


def api_error(payload: Any) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    description = payload.get("description") or payload.get("detail")
    if error is None and description is None:
        return None
    combined = f"{error or ''} {description or ''}".lower()
    if not any(token in combined for token in ("error", "bad request", "invalid")):
        return None
    return {
        "error": str(error or ""),
        "description": str(description or "")[:1000],
    }


def summarize_payload_shape(payload: Any) -> dict[str, object]:
    summary: dict[str, object] = {"payload_type": type(payload).__name__}
    if isinstance(payload, dict):
        summary["top_level_keys"] = sorted(str(key) for key in payload)[:100]
        for key in ("sqlid", "sql_id", "id", "count", "status"):
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                if key in payload:
                    summary[key] = value
    elif isinstance(payload, list):
        summary["row_count"] = len(payload)
        if payload and isinstance(payload[0], dict):
            summary["first_row_keys"] = sorted(str(key) for key in payload[0])[:100]
    return summary


def submit_sql(
    openapi_root: str,
    *,
    dr_version: str,
    sub_version: str,
    sql: str,
    output_format: str = "json",
    token: str | None = None,
    timeout: float = 60.0,
    retries: int = 2,
    maximum_response_bytes: int = 16 * 1024 * 1024,
    opener: Any = urlopen,
) -> tuple[Any, SQLReceipt]:
    """Submit one SQL query through the first-party public OpenAPI endpoint."""

    statement = sql.strip()
    if not statement:
        raise ValueError("sql must not be empty")
    root = openapi_root.rstrip("/")
    endpoint = f"{root}/{dr_version}/{sub_version}/sql"
    payload, receipt = _fetch_json_get(
        endpoint,
        params={
            "sql": statement,
            "output.fmt": output_format,
            "token": token,
        },
        timeout=timeout,
        retries=retries,
        maximum_response_bytes=maximum_response_bytes,
        opener=opener,
    )
    error = api_error(payload)
    if error is not None:
        raise LAMOSTSQLError(f"LAMOST SQL API error: {error}")
    return payload, receipt


def probe_public_sql_protocol(
    *,
    openapi_root: str,
    dr_version: str = "dr8",
    sub_version: str = "v1.0",
    timeout: float = 60.0,
    retries: int = 2,
    maximum_response_bytes: int = 16 * 1024 * 1024,
    opener: Any = urlopen,
) -> dict[str, object]:
    """Probe the public SQL transport with a constant query containing no source data."""

    sql = "SELECT 1 AS hou_compact_probe"
    payload, receipt = submit_sql(
        openapi_root,
        dr_version=dr_version,
        sub_version=sub_version,
        sql=sql,
        timeout=timeout,
        retries=retries,
        maximum_response_bytes=maximum_response_bytes,
        opener=opener,
    )
    return {
        "status": "pass",
        "release": f"{dr_version}/{sub_version}",
        "query_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "receipt": receipt.to_record(),
        "response_shape": summarize_payload_shape(payload),
        "response": payload,
        "claim_boundary": (
            "The probe executes SELECT 1 only. It contains no catalogue table, "
            "source identifier, coordinate, spectrum, or candidate information."
        ),
    }
