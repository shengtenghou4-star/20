"""Exact NOIRLab Data Lab Query Manager adapter for Gaia–DESI overlap.

The public Data Lab Python client treats ``https://datalab.noirlab.edu/query`` as
its service URL and submits SQL to the nested ``/query`` endpoint.  This module
mirrors that wire contract while retaining HOU-COMPACT's bounded, candidate-safe
validation and provenance receipts.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from hou_compact.datalab import (
    DataLabBatchReceipt,
    DataLabQueryConfig,
    DataLabQueryError,
    build_desi_gaia_overlap_sql,
    parse_desi_gaia_overlap_csv,
)


def query_manager_endpoint(service_url: str) -> str:
    """Return the Query Manager's concrete SQL submission endpoint.

    Data Lab's official client defaults its service URL to ``.../query`` and then
    appends another ``/query`` for submissions.  Accepting a root, service root,
    or full endpoint keeps configuration explicit without ever producing a third
    repeated path component.
    """
    root = service_url.rstrip("/")
    if root.endswith("/query/query"):
        return root
    if root.endswith("/query"):
        return f"{root}/query"
    return f"{root}/query/query"


def query_manager_url(config: DataLabQueryConfig, sql: str) -> str:
    """Build a synchronous CSV URL matching the official Data Lab client."""
    parameters = urlencode(
        {
            "sql": sql,
            "ofmt": "csv",
            "out": "None",
            "async": "False",
            "drop": "False",
            "profile": config.profile,
        }
    )
    return f"{query_manager_endpoint(config.service_url)}?{parameters}"


def request_headers(config: DataLabQueryConfig) -> dict[str, str]:
    """Return the minimal official Query Manager request headers."""
    return {
        "User-Agent": "HOU-COMPACT/0.1 exact Gaia-DESI overlap",
        "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
        "Content-Type": "text/ascii",
        "X-DL-TimeoutRequest": str(int(config.timeout_seconds)),
        "X-DL-ClientVersion": "hou-compact-0.1",
        "X-DL-AuthToken": config.token,
    }


def _read_bounded(response: Any, maximum_bytes: int) -> bytes:
    body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise DataLabQueryError(
            f"Data Lab response exceeded byte limit {maximum_bytes}"
        )
    return body


def _decode_response(body: bytes) -> str:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DataLabQueryError("Data Lab response was not UTF-8 text") from error
    stripped = text.lstrip()
    lowered = stripped.lower()
    if not stripped:
        raise DataLabQueryError("Data Lab returned an empty response")
    if lowered.startswith(("error", "traceback", "<!doctype html", "<html")):
        excerpt = " ".join(stripped[:1000].split())
        raise DataLabQueryError(f"Data Lab service error: {excerpt}")
    return text


def execute_query_manager_csv(
    sql: str,
    *,
    config: DataLabQueryConfig = DataLabQueryConfig(),
    opener: Callable[..., Any] = urlopen,
) -> tuple[str, int]:
    """Execute one bounded anonymous SELECT through the Query Manager."""
    if not sql.strip().lower().startswith("select"):
        raise ValueError("only SELECT queries are permitted")
    request = Request(
        query_manager_url(config, sql),
        headers=request_headers(config),
    )
    last_error: BaseException | None = None
    for attempt in range(config.retries + 1):
        try:
            with opener(request, timeout=config.timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise DataLabQueryError(f"Data Lab returned HTTP {status}")
                body = _read_bounded(response, config.maximum_response_bytes)
            return _decode_response(body), attempt + 1
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= config.retries:
                raise DataLabQueryError(
                    f"Data Lab HTTP error {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= config.retries:
                raise DataLabQueryError(
                    f"Data Lab transport error: {type(error).__name__}: {error}"
                ) from error
        except DataLabQueryError:
            raise
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise DataLabQueryError(str(last_error))


def _parse_with_safe_diagnostics(text: str) -> pd.DataFrame:
    try:
        return parse_desi_gaia_overlap_csv(text)
    except DataLabQueryError as error:
        first_line = text.splitlines()[0].strip() if text.splitlines() else ""
        safe_header = first_line[:500]
        response_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        raise DataLabQueryError(
            f"{error}; response_sha256={response_sha256}; "
            f"first_line={safe_header!r}"
        ) from error


def query_desi_gaia_overlap_v2(
    source_ids: Iterable[int],
    *,
    survey: str = "main",
    programs: Sequence[str] = ("bright", "dark"),
    config: DataLabQueryConfig = DataLabQueryConfig(),
    opener: Callable[..., Any] = urlopen,
) -> tuple[pd.DataFrame, list[DataLabBatchReceipt]]:
    """Return exact Gaia-source/DESI-TARGETID mappings in bounded batches."""
    identifiers = sorted({int(value) for value in source_ids})
    if any(value < 0 or value > 2**63 - 1 for value in identifiers):
        raise ValueError("Gaia source ID outside signed 64-bit range")
    columns = [
        "source_id",
        "targetid",
        "survey",
        "program",
        "healpix",
        "match_distance_arcsec",
    ]
    if not identifiers:
        return pd.DataFrame(columns=columns), []

    frames: list[pd.DataFrame] = []
    receipts: list[DataLabBatchReceipt] = []
    for batch_index, start in enumerate(
        range(0, len(identifiers), config.batch_size)
    ):
        batch = identifiers[start : start + config.batch_size]
        batch_set = set(batch)
        sql = build_desi_gaia_overlap_sql(
            batch,
            survey=survey,
            programs=programs,
        )
        text, attempts = execute_query_manager_csv(
            sql,
            config=config,
            opener=opener,
        )
        frame = _parse_with_safe_diagnostics(text)
        unexpected = sorted(set(frame["source_id"].astype(int)) - batch_set)
        if unexpected:
            raise DataLabQueryError(
                "Data Lab returned source IDs outside the current batch: "
                f"{unexpected[:5]}"
            )
        if (frame["match_distance_arcsec"] > 1.5 + 1e-9).any():
            raise DataLabQueryError(
                "official 1.5-arcsec table returned a larger distance"
            )
        encoded = text.encode("utf-8")
        receipts.append(
            DataLabBatchReceipt(
                batch_index=batch_index,
                requested_source_count=len(batch),
                returned_row_count=len(frame),
                returned_source_count=int(frame["source_id"].nunique()),
                query_sha256=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                response_sha256=hashlib.sha256(encoded).hexdigest(),
                response_bytes=len(encoded),
                attempts=attempts,
            )
        )
        frames.append(frame)

    result = pd.concat(frames, ignore_index=True)
    if not result.empty:
        key = ["source_id", "targetid", "survey", "program", "healpix"]
        result = (
            result.sort_values(key + ["match_distance_arcsec"], kind="stable")
            .drop_duplicates(key, keep="first")
            .reset_index(drop=True)
        )
    return result, receipts
