"""Exact Gaia DR3 to DESI DR1 zpix overlap queries through NOIRLab Data Lab."""

from __future__ import annotations

import hashlib
import io
import math
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

DATALAB_QUERY_SERVICE = "https://datalab.noirlab.edu"
DATALAB_ANONYMOUS_TOKEN = "anonymous.0.0.anon_access"
GAIA_DESI_XMATCH_TABLE = "gaia_dr3.x1p5__gaia_source__desi_dr1__zpix"
DESI_ZPIX_TABLE = "desi_dr1.zpix"
_SAFE_SQL_LITERAL = re.compile(r"^[A-Za-z0-9_]+$")
_EXPECTED_COLUMNS = (
    "source_id",
    "targetid",
    "survey",
    "program",
    "healpix",
    "match_distance_arcsec",
)


class DataLabQueryError(RuntimeError):
    """Raised when Data Lab returns a transport, service, or schema error."""


@dataclass(frozen=True)
class DataLabQueryConfig:
    """Bounded synchronous-query settings for public Data Lab tables."""

    service_url: str = DATALAB_QUERY_SERVICE
    token: str = DATALAB_ANONYMOUS_TOKEN
    profile: str = "default"
    timeout_seconds: float = 120.0
    retries: int = 2
    maximum_response_bytes: int = 16 * 1024 * 1024
    batch_size: int = 150

    def __post_init__(self) -> None:
        if not self.service_url.startswith("https://"):
            raise ValueError("service_url must use HTTPS")
        if not self.token or any(character in self.token for character in "\r\n"):
            raise ValueError("token must be a non-empty single-line value")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if self.retries < 0:
            raise ValueError("retries must be non-negative")
        if self.maximum_response_bytes < 1024:
            raise ValueError("maximum_response_bytes must be at least 1024")
        if not 1 <= self.batch_size <= 500:
            raise ValueError("batch_size must lie in [1, 500]")


@dataclass(frozen=True)
class DataLabBatchReceipt:
    """Candidate-safe provenance for one exact-overlap query batch."""

    batch_index: int
    requested_source_count: int
    returned_row_count: int
    returned_source_count: int
    query_sha256: str
    response_sha256: str
    response_bytes: int
    attempts: int

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _validated_source_ids(source_ids: Iterable[int]) -> list[int]:
    values: set[int] = set()
    for raw in source_ids:
        if isinstance(raw, bool):
            raise TypeError("Gaia source IDs must be integers, not booleans")
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise TypeError(f"invalid Gaia source ID: {raw!r}") from error
        if value < 0 or value > 2**63 - 1:
            raise ValueError(
                f"Gaia source ID outside signed 64-bit range: {value}"
            )
        values.add(value)
    return sorted(values)


def _validated_sql_literals(
    values: Sequence[str],
    *,
    name: str,
) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(value).strip() for value in values))
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    unsafe = [
        value for value in normalized if not _SAFE_SQL_LITERAL.fullmatch(value)
    ]
    if unsafe:
        raise ValueError(f"unsafe {name} SQL literal(s): {unsafe}")
    return normalized


def build_desi_gaia_overlap_sql(
    source_ids: Iterable[int],
    *,
    survey: str = "main",
    programs: Sequence[str] = ("bright", "dark"),
) -> str:
    """Build one exact reverse-crossmatch query without lossy numeric casts."""
    identifiers = _validated_source_ids(source_ids)
    if not identifiers:
        raise ValueError("source_ids must not be empty")
    survey_literal = _validated_sql_literals((survey,), name="survey")[0]
    program_literals = _validated_sql_literals(programs, name="programs")
    identifier_list = ",".join(str(value) for value in identifiers)
    program_list = ",".join(f"'{value}'" for value in program_literals)
    return "\n".join(
        [
            "SELECT",
            "    x.id1 AS source_id,",
            "    z.targetid AS targetid,",
            "    z.survey AS survey,",
            "    z.program AS program,",
            "    z.healpix AS healpix,",
            "    x.distance AS match_distance_arcsec",
            f"FROM {GAIA_DESI_XMATCH_TABLE} AS x",
            f"JOIN {DESI_ZPIX_TABLE} AS z ON x.id2 = z.id",
            f"WHERE x.id1 IN ({identifier_list})",
            f"  AND z.survey = '{survey_literal}'",
            f"  AND z.program IN ({program_list})",
            "ORDER BY x.id1, z.survey, z.program, z.healpix, z.targetid",
        ]
    )


def _query_url(config: DataLabQueryConfig, sql: str) -> str:
    parameters = urlencode(
        {
            "sql": sql,
            "ofmt": "csv",
            "out": "",
            "async_": "False",
            "profile": config.profile,
        }
    )
    root = config.service_url.rstrip("/")
    endpoint = root if root.endswith("/query") else f"{root}/query"
    return f"{endpoint}?{parameters}"


def _request_headers(config: DataLabQueryConfig) -> dict[str, str]:
    return {
        "User-Agent": "HOU-COMPACT/0.1 exact Gaia-DESI overlap",
        "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
        "X-DL-ClientVersion": "hou-compact-0.1",
        "X-DL-User": "anonymous",
        "X-DL-AuthToken": config.token,
    }


def _response_body(response: Any, maximum_bytes: int) -> bytes:
    body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise DataLabQueryError(
            f"Data Lab response exceeded byte limit {maximum_bytes}"
        )
    return body


def _validate_csv_payload(body: bytes) -> str:
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


def execute_sync_csv_query(
    sql: str,
    *,
    config: DataLabQueryConfig = DataLabQueryConfig(),
    opener: Callable[..., Any] = urlopen,
) -> tuple[str, int]:
    """Execute one bounded anonymous SELECT query and return CSV plus attempts."""
    if not sql.strip().lower().startswith("select"):
        raise ValueError("only SELECT queries are permitted")
    request = Request(_query_url(config, sql), headers=_request_headers(config))
    last_error: BaseException | None = None
    for attempt in range(config.retries + 1):
        try:
            with opener(request, timeout=config.timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise DataLabQueryError(f"Data Lab returned HTTP {status}")
                body = _response_body(
                    response,
                    config.maximum_response_bytes,
                )
            return _validate_csv_payload(body), attempt + 1
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= config.retries:
                raise DataLabQueryError(
                    f"Data Lab HTTP error {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError, DataLabQueryError) as error:
            last_error = error
            if isinstance(error, DataLabQueryError) or attempt >= config.retries:
                raise DataLabQueryError(str(error)) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise DataLabQueryError(str(last_error))


def parse_desi_gaia_overlap_csv(text: str) -> pd.DataFrame:
    """Parse and strictly validate a Data Lab exact-overlap CSV response."""
    try:
        frame = pd.read_csv(io.StringIO(text), dtype=str)
    except pd.errors.ParserError as error:
        raise DataLabQueryError("Data Lab CSV could not be parsed") from error
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    missing = sorted(set(_EXPECTED_COLUMNS) - set(frame.columns))
    if missing:
        raise DataLabQueryError(
            f"Data Lab response is missing columns: {missing}"
        )
    frame = frame.loc[:, list(_EXPECTED_COLUMNS)].copy()
    if frame.empty:
        return frame.astype(
            {
                "source_id": "int64",
                "targetid": "int64",
                "survey": "object",
                "program": "object",
                "healpix": "int64",
                "match_distance_arcsec": "float64",
            }
        )
    for name in ("source_id", "targetid", "healpix"):
        numeric = pd.to_numeric(frame[name], errors="raise")
        if (numeric % 1 != 0).any():
            raise DataLabQueryError(f"non-integral value in {name}")
        frame[name] = numeric.astype("int64")
    frame["match_distance_arcsec"] = pd.to_numeric(
        frame["match_distance_arcsec"],
        errors="raise",
    ).astype(float)
    if not frame["match_distance_arcsec"].map(math.isfinite).all():
        raise DataLabQueryError("non-finite crossmatch distance returned")
    if (frame["match_distance_arcsec"] < 0).any():
        raise DataLabQueryError("negative crossmatch distance returned")
    for name in ("survey", "program"):
        frame[name] = frame[name].astype(str).str.strip().str.lower()
    return frame


def query_desi_gaia_overlap(
    source_ids: Iterable[int],
    *,
    survey: str = "main",
    programs: Sequence[str] = ("bright", "dark"),
    config: DataLabQueryConfig = DataLabQueryConfig(),
    opener: Callable[..., Any] = urlopen,
) -> tuple[pd.DataFrame, list[DataLabBatchReceipt]]:
    """Return Gaia-source/DESI-TARGETID mappings in deterministic batches."""
    identifiers = _validated_source_ids(source_ids)
    columns = list(_EXPECTED_COLUMNS)
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
        text, attempts = execute_sync_csv_query(
            sql,
            config=config,
            opener=opener,
        )
        frame = parse_desi_gaia_overlap_csv(text)
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
        response_bytes = len(text.encode("utf-8"))
        receipts.append(
            DataLabBatchReceipt(
                batch_index=batch_index,
                requested_source_count=len(batch),
                returned_row_count=len(frame),
                returned_source_count=int(frame["source_id"].nunique()),
                query_sha256=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                response_sha256=hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest(),
                response_bytes=response_bytes,
                attempts=attempts,
            )
        )
        frames.append(frame)
    result = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=columns)
    )
    if not result.empty:
        key = ["source_id", "targetid", "survey", "program", "healpix"]
        result = result.sort_values(
            key + ["match_distance_arcsec"],
            kind="stable",
        ).drop_duplicates(key, keep="first")
        result = result.reset_index(drop=True)
    return result, receipts
