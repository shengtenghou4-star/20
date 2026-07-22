#!/usr/bin/env python3
"""Verify the official LAMOST DR8 v1.0 multiple-epoch catalogue contract.

The former implementation queried ``tap.china-vo.org`` as an IVOA TAP
service. That hostname belongs to China-VO's Telescope Access Program, not a
Table Access Protocol endpoint. This probe therefore validates the two
first-party LAMOST resources that actually define and expose the catalogue:
the catalogue download page and the low-resolution data-description page.
It reads metadata/documentation only and never requests source rows.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CATALOGUE_URL = "https://www.lamost.org/dr8/v1.0/catalogue"
DEFAULT_DOCUMENTATION_URL = (
    "https://www.lamost.org/dr8/v1.0/doc/lr-data-production-description"
)
MAXIMUM_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class FetchReceipt:
    url: str
    status: int
    attempts: int
    response_bytes: int
    sha256: str


class ContractProbeError(RuntimeError):
    """Raised when an official metadata resource cannot verify the contract."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue-url", default=DEFAULT_CATALOGUE_URL)
    parser.add_argument("--documentation-url", default=DEFAULT_DOCUMENTATION_URL)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--maximum-response-bytes",
        type=int,
        default=MAXIMUM_RESPONSE_BYTES,
    )
    return parser.parse_args()


def fetch_text(
    url: str,
    *,
    timeout: float,
    retries: int,
    maximum_response_bytes: int,
    opener: Any = urlopen,
) -> tuple[str, FetchReceipt]:
    if not url.startswith("https://"):
        raise ValueError("LAMOST metadata URLs must use HTTPS")
    if timeout <= 0 or retries < 0:
        raise ValueError("timeout/retry settings are invalid")
    if maximum_response_bytes < 1024:
        raise ValueError("maximum_response_bytes must be at least 1024")

    request = Request(
        url,
        headers={
            "User-Agent": "HOU-COMPACT/0.1 LAMOST DR8 contract probe",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
    )
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise ContractProbeError(
                        f"official LAMOST resource returned HTTP {status}"
                    )
                body = response.read(maximum_response_bytes + 1)
            if len(body) > maximum_response_bytes:
                raise ContractProbeError(
                    "official LAMOST metadata response exceeded the byte limit"
                )
            try:
                text = body.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = body.decode("latin-1")
            if not text.strip():
                raise ContractProbeError(
                    "official LAMOST resource returned an empty body"
                )
            receipt = FetchReceipt(
                url=url,
                status=status,
                attempts=attempt + 1,
                response_bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
            )
            return text, receipt
        except HTTPError as error:
            last_error = error
            retryable = error.code == 429 or error.code >= 500
            if not retryable or attempt >= retries:
                raise ContractProbeError(
                    f"official LAMOST resource returned HTTP {error.code}"
                ) from error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= retries:
                raise ContractProbeError(
                    "official LAMOST transport error: "
                    f"{type(error).__name__}: {error}"
                ) from error
        time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise ContractProbeError(str(last_error))


def visible_text(document: str) -> str:
    without_scripts = re.sub(
        r"(?is)<(?:script|style)\b.*?</(?:script|style)>",
        " ",
        document,
    )
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return " ".join(html.unescape(without_tags).split()).lower()


def require_markers(text: str, markers: tuple[str, ...], *, resource: str) -> None:
    missing = [marker for marker in markers if marker.lower() not in text]
    if missing:
        raise ContractProbeError(
            f"{resource} is missing required contract markers: {missing}"
        )


def main() -> None:
    args = parse_args()
    catalogue_html, catalogue_receipt = fetch_text(
        args.catalogue_url,
        timeout=args.timeout,
        retries=args.retries,
        maximum_response_bytes=args.maximum_response_bytes,
    )
    documentation_html, documentation_receipt = fetch_text(
        args.documentation_url,
        timeout=args.timeout,
        retries=args.retries,
        maximum_response_bytes=args.maximum_response_bytes,
    )

    catalogue_text = visible_text(catalogue_html)
    documentation_text = visible_text(documentation_html)
    catalogue_markers = (
        "LAMOST LRS Multiple Epoch Catalog",
        "Low Resolution Catalog",
    )
    contract_markers = (
        "Gaia DR2",
        "gaia_source_id",
        "obs_number",
        "obsid_list",
        "midmjm_list",
        "rv_list",
    )
    require_markers(catalogue_text, catalogue_markers, resource="catalogue page")
    require_markers(
        documentation_text,
        contract_markers,
        resource="data-description page",
    )

    payload = {
        "status": "pass",
        "release": "LAMOST DR8 v1.0",
        "catalogue": "LAMOST LRS Multiple Epoch Catalog",
        "identity_release": "Gaia DR2",
        "catalogue_page_receipt": asdict(catalogue_receipt),
        "documentation_page_receipt": asdict(documentation_receipt),
        "verified_catalogue_markers": sorted(catalogue_markers),
        "verified_contract_columns": sorted(
            marker for marker in contract_markers if marker != "Gaia DR2"
        ),
        "claim_boundary": (
            "This live probe verifies first-party catalogue availability and the "
            "documented identity/epoch field contract only. It requests no source "
            "rows and establishes no Gaia overlap or orbit result."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
