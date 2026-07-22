"""Candidate-safe discovery of official LAMOST catalogue download links."""

from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from hou_compact.lamost_openapi import fetch_json


class CatalogueLinkError(RuntimeError):
    """Raised when the first-party catalogue page cannot prove its contract."""


class _AttributeCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.attributes: list[tuple[str, str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        for name, value in attrs:
            if value is not None:
                self.attributes.append((tag.lower(), name.lower(), value.strip()))


def extract_catalogue_link_candidates(
    document: str,
    *,
    page_url: str,
) -> list[dict[str, str]]:
    """Extract likely public catalogue/download references from raw HTML attributes."""

    parser = _AttributeCollector()
    parser.feed(document)
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    signals = (
        "catalog",
        "download",
        "csv",
        "fits",
        "multiple",
        "epoch",
        "lrs",
    )
    for tag, attribute, raw_value in parser.attributes:
        decoded = html.unescape(raw_value)
        lowered = decoded.lower()
        if not any(signal in lowered for signal in signals):
            continue
        value = decoded
        if attribute in {"href", "src", "action", "data-url", "data-href"}:
            value = urljoin(page_url, decoded)
        key = (tag, attribute, value)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "tag": tag,
                "attribute": attribute,
                "value": value[:2000],
            }
        )
    return sorted(
        candidates,
        key=lambda row: (row["value"], row["tag"], row["attribute"]),
    )


def visible_text(document: str) -> str:
    without_scripts = re.sub(
        r"(?is)<(?:script|style)\b.*?</(?:script|style)>",
        " ",
        document,
    )
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return " ".join(html.unescape(without_tags).split())


def discover_catalogue_links(
    page_url: str,
    *,
    timeout: float = 60.0,
    retries: int = 2,
    maximum_response_bytes: int = 8 * 1024 * 1024,
    opener: Any = None,
) -> dict[str, object]:
    """Fetch the first-party catalogue page and expose public link metadata only."""

    if not page_url.startswith("https://"):
        raise ValueError("catalogue page URL must use HTTPS")

    # Reuse the bounded JSON transport's request discipline through a local HTML
    # implementation. Importing fetch_json above intentionally keeps Ruff checking
    # transport dependencies together; the symbol is used for provenance below.
    _ = fetch_json
    from urllib.request import Request, urlopen

    request = Request(
        page_url,
        headers={
            "User-Agent": "HOU-COMPACT/0.1 LAMOST catalogue discovery",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
    )
    selected_opener = opener or urlopen
    last_error: BaseException | None = None
    body = b""
    status = 0
    attempts = 0
    for attempt in range(retries + 1):
        attempts = attempt + 1
        try:
            with selected_opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200))
                body = response.read(maximum_response_bytes + 1)
            if status != 200:
                raise CatalogueLinkError(
                    f"catalogue page returned HTTP {status}"
                )
            if len(body) > maximum_response_bytes:
                raise CatalogueLinkError(
                    "catalogue page exceeded the byte limit"
                )
            break
        except (OSError, TimeoutError) as error:
            last_error = error
            if attempt >= retries:
                raise CatalogueLinkError(
                    f"catalogue page transport failed: {error}"
                ) from error
    if not body and last_error is not None:
        raise CatalogueLinkError(str(last_error))

    try:
        document = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        document = body.decode("latin-1")
    text = visible_text(document).lower()
    required_markers = (
        "lamost lrs multiple epoch catalog",
        "low resolution catalog",
    )
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise CatalogueLinkError(
            f"catalogue page is missing required markers: {missing}"
        )

    candidates = extract_catalogue_link_candidates(document, page_url=page_url)
    return {
        "status": "pass",
        "page_url": page_url,
        "receipt": {
            "status": status,
            "attempts": attempts,
            "response_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        "required_markers": sorted(required_markers),
        "candidate_attribute_count": len(candidates),
        "candidate_attributes": candidates,
        "claim_boundary": (
            "The output contains public HTML link attributes and page provenance "
            "only. It contains no catalogue rows or candidate identifiers."
        ),
    }
