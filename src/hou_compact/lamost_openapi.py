"""Bounded, candidate-safe discovery of the public LAMOST OpenAPI contract."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_OPENAPI_ROOT = "https://www.lamost.org/openapi"
REQUIRED_MULTIEPOCH_COLUMNS = (
    "gaia_source_id",
    "obs_number",
    "obsid_list",
    "midmjm_list",
    "rv_list",
)


class LAMOSTOpenAPIError(RuntimeError):
    """Raised when public LAMOST OpenAPI metadata violates the contract."""


@dataclass(frozen=True)
class JSONReceipt:
    """Immutable provenance for one bounded metadata request."""

    url: str
    status: int
    attempts: int
    response_bytes: int
    sha256: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def fetch_json(
    url: str,
    *,
    timeout: float = 60.0,
    retries: int = 2,
    maximum_response_bytes: int = 16 * 1024 * 1024,
    opener: Any = urlopen,
) -> tuple[Any, JSONReceipt]:
    """Fetch and parse one HTTPS JSON resource with strict bounds and receipts."""

    if not url.startswith("https://"):
        raise ValueError("OpenAPI URLs must use HTTPS")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if maximum_response_bytes < 1024:
        raise ValueError("maximum_response_bytes must be at least 1024")

    request = Request(
        url,
        headers={
            "User-Agent": "HOU-COMPACT/0.1 LAMOST OpenAPI metadata probe",
            "Accept": "application/json,*/*;q=0.1",
        },
    )
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise LAMOSTOpenAPIError(
                        f"LAMOST OpenAPI returned HTTP {status}"
                    )
                body = response.read(maximum_response_bytes + 1)
            if len(body) > maximum_response_bytes:
                raise LAMOSTOpenAPIError(
                    "LAMOST OpenAPI response exceeded the byte limit"
                )
            try:
                payload = json.loads(body.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise LAMOSTOpenAPIError(
                    "LAMOST OpenAPI response was not valid UTF-8 JSON"
                ) from error
            receipt = JSONReceipt(
                url=url,
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
                raise LAMOSTOpenAPIError(
                    f"LAMOST OpenAPI returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise LAMOSTOpenAPIError(
                    "LAMOST OpenAPI transport error: "
                    f"{type(error).__name__}: {error}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise LAMOSTOpenAPIError(str(last_error))


def iter_scalars(value: Any) -> list[str]:
    """Flatten JSON keys and scalar values into deterministic text tokens."""

    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            result.append(str(key))
            result.extend(iter_scalars(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            result.extend(iter_scalars(item))
    elif value is not None:
        result.append(str(value))
    return result


def candidate_metadata_nodes(value: Any) -> list[dict[str, Any]]:
    """Return metadata dictionaries that look like the LRS multiple-epoch table."""

    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        flattened = " ".join(iter_scalars(value)).lower()
        column_hits = sum(
            column in flattened for column in REQUIRED_MULTIEPOCH_COLUMNS
        )
        name_hit = "multiple" in flattened and "epoch" in flattened
        if name_hit or column_hits >= 3:
            matches.append(value)
        for item in value.values():
            matches.extend(candidate_metadata_nodes(item))
    elif isinstance(value, list):
        for item in value:
            matches.extend(candidate_metadata_nodes(item))
    return matches


def safe_metadata_summary(node: dict[str, Any]) -> dict[str, Any]:
    """Keep only public schema descriptors and suppress arbitrary nested records."""

    summary: dict[str, Any] = {}
    for key, value in node.items():
        lowered = str(key).lower()
        if not any(
            token in lowered
            for token in ("table", "name", "column", "field", "description")
        ):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[str(key)] = value
        elif isinstance(value, list):
            safe_items = [
                item
                for item in value
                if isinstance(item, (str, int, float, bool)) or item is None
            ]
            if safe_items:
                summary[str(key)] = safe_items[:100]
    if summary:
        return summary
    digest = hashlib.sha256(
        json.dumps(node, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {"metadata_sha256": digest}


def extract_tap_urls(payload: Any) -> list[str]:
    """Extract unique HTTPS TAP URLs from an arbitrary OpenAPI JSON payload."""

    urls = {
        value.strip()
        for value in iter_scalars(payload)
        if value.strip().startswith("https://") and "tap" in value.lower()
    }
    return sorted(urls)


def discover_openapi_contract(
    *,
    openapi_root: str = DEFAULT_OPENAPI_ROOT,
    dr_version: str = "dr8",
    sub_version: str = "v1.0",
    timeout: float = 60.0,
    retries: int = 2,
    maximum_response_bytes: int = 16 * 1024 * 1024,
) -> dict[str, object]:
    """Verify public release, table metadata, and the official TAP endpoint."""

    root = openapi_root.rstrip("/")
    if not root.startswith("https://"):
        raise ValueError("openapi_root must use HTTPS")
    version_root = f"{root}/{dr_version}/{sub_version}"
    endpoints = {
        "versions": f"{root}/dr_versions",
        "tables": f"{version_root}/tables",
        "tap": f"{version_root}/voservice/tap_url",
    }
    payloads: dict[str, Any] = {}
    receipts: dict[str, JSONReceipt] = {}
    for name, url in endpoints.items():
        payloads[name], receipts[name] = fetch_json(
            url,
            timeout=timeout,
            retries=retries,
            maximum_response_bytes=maximum_response_bytes,
        )

    version_text = " ".join(iter_scalars(payloads["versions"])).lower()
    if dr_version.lower() not in version_text or sub_version.lower() not in version_text:
        raise LAMOSTOpenAPIError(
            f"{dr_version}/{sub_version} absent from public version metadata"
        )

    table_text = " ".join(iter_scalars(payloads["tables"])).lower()
    missing_columns = [
        column
        for column in REQUIRED_MULTIEPOCH_COLUMNS
        if column not in table_text
    ]
    if missing_columns:
        raise LAMOSTOpenAPIError(
            f"LAMOST table metadata is missing required columns: {missing_columns}"
        )
    nodes = candidate_metadata_nodes(payloads["tables"])
    if not nodes:
        raise LAMOSTOpenAPIError(
            "no multiple-epoch table metadata node was discovered"
        )

    tap_urls = extract_tap_urls(payloads["tap"])
    if not tap_urls:
        raise LAMOSTOpenAPIError(
            "OpenAPI did not return an HTTPS TAP service URL"
        )

    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in nodes:
        summary = safe_metadata_summary(node)
        key = json.dumps(summary, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            summaries.append(summary)

    return {
        "status": "pass",
        "release": f"{dr_version}/{sub_version}",
        "openapi_root": root,
        "receipts": {
            name: receipt.to_record() for name, receipt in receipts.items()
        },
        "required_columns": sorted(REQUIRED_MULTIEPOCH_COLUMNS),
        "candidate_metadata_nodes": summaries[:20],
        "tap_urls": tap_urls,
        "claim_boundary": (
            "This probe accesses public metadata only. It returns no source rows, "
            "Gaia identifiers, radial velocities, or candidate classifications."
        ),
    }
