#!/usr/bin/env python3
"""Extract candidate-safe public query metadata from LAMOST documentation.

This probe fetches only the official OpenAPI specification and low-resolution
search HTML. It records bounded schema blocks, form actions/methods, field names,
script URLs, endpoint-like strings, byte counts, and hashes. It never submits a
catalogue query or sends a source identifier, coordinate, or radial velocity.
"""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


class _SearchHTMLParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.forms: list[dict[str, Any]] = []
        self.scripts: list[str] = []
        self.inline_scripts: list[str] = []
        self._current_form: dict[str, Any] | None = None
        self._inside_script = False
        self._script_chunks: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).lower(): str(value or "") for key, value in attrs}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = self._attrs(attrs)
        lowered = tag.lower()
        if lowered == "form":
            form = {
                "action": urljoin(self.base_url, values.get("action", "")),
                "method": values.get("method", "get").lower(),
                "enctype": values.get("enctype", ""),
                "id": values.get("id", ""),
                "name": values.get("name", ""),
                "fields": [],
            }
            self.forms.append(form)
            self._current_form = form
        elif lowered in {"input", "select", "textarea", "button"}:
            name = values.get("name", "").strip()
            if self._current_form is not None and name:
                self._current_form["fields"].append(
                    {
                        "tag": lowered,
                        "name": name,
                        "type": values.get("type", "").lower(),
                    }
                )
        elif lowered == "script":
            source = values.get("src", "").strip()
            if source:
                self.scripts.append(urljoin(self.base_url, source))
            else:
                self._inside_script = True
                self._script_chunks = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "form":
            self._current_form = None
        elif lowered == "script" and self._inside_script:
            text = "".join(self._script_chunks).strip()
            if text:
                self.inline_scripts.append(text)
            self._inside_script = False
            self._script_chunks = []

    def handle_data(self, data: str) -> None:
        if self._inside_script:
            self._script_chunks.append(data)


def _fetch_text(
    url: str,
    *,
    timeout: float,
    maximum_bytes: int,
) -> tuple[str, dict[str, object]]:
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 public metadata probe",
            "Accept": "text/html,application/yaml,text/yaml,text/plain,*/*;q=0.1",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        content_type = str(response.headers.get("Content-Type", ""))
        body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise RuntimeError(f"public metadata response exceeded {maximum_bytes} bytes")
    if status != 200:
        raise RuntimeError(f"public metadata endpoint returned HTTP {status}")
    text = body.decode("utf-8-sig", errors="strict")
    return text, {
        "url": url,
        "status": status,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _extract_indented_block(
    text: str,
    heading_pattern: str,
    *,
    maximum_lines: int = 240,
) -> list[str]:
    lines = text.splitlines()
    matcher = re.compile(heading_pattern)
    start: int | None = None
    indentation = 0
    for index, line in enumerate(lines):
        if matcher.search(line):
            start = index
            indentation = len(line) - len(line.lstrip(" "))
            break
    if start is None:
        return []
    output = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip():
            current_indent = len(line) - len(line.lstrip(" "))
            if current_indent <= indentation:
                break
        output.append(line)
        if len(output) >= maximum_lines:
            output.append("# [truncated]")
            break
    return output


def extract_openapi_contract(spec_text: str) -> dict[str, object]:
    path_block = _extract_indented_block(
        spec_text,
        r"^\s*/openapi/\{dr_version\}/\{sub_version\}/query/\{table_name\}:\s*$",
        maximum_lines=320,
    )
    schemas: dict[str, list[str]] = {}
    for name in (
        "TableQuery",
        "ColumnConstraint",
        "PositionConstraint",
        "ConePosition",
        "RectanglePosition",
        "ProximityPosition",
        "NoPosition",
    ):
        schemas[name] = _extract_indented_block(
            spec_text,
            rf"^\s{{4}}{re.escape(name)}:\s*$",
            maximum_lines=240,
        )
    return {
        "query_table_path_block": path_block,
        "schemas": schemas,
        "query_table_path_found": bool(path_block),
        "schema_blocks_found": {
            name: bool(block) for name, block in schemas.items()
        },
    }


def _same_origin_endpoint_candidates(
    scripts: list[str],
    inline_scripts: list[str],
    base_url: str,
) -> list[str]:
    origin = urlparse(base_url)
    candidates: set[str] = set()
    quoted = re.compile(
        r"[\"']((?:https?://[^\"']+)|(?:/[^\"']*(?:query|search|result|download|api)[^\"']*))[\"']",
        flags=re.IGNORECASE,
    )
    for text in inline_scripts:
        for match in quoted.finditer(text):
            candidate = urljoin(base_url, match.group(1))
            parsed = urlparse(candidate)
            if parsed.scheme in {"http", "https"} and parsed.netloc == origin.netloc:
                candidates.add(candidate)
    for source in scripts:
        parsed = urlparse(source)
        if parsed.netloc == origin.netloc:
            candidates.add(source)
    return sorted(candidates)[:200]


def extract_search_contract(html_text: str, search_url: str) -> dict[str, object]:
    parser = _SearchHTMLParser(search_url)
    parser.feed(html_text)
    forms = []
    for form in parser.forms[:50]:
        unique_fields = {
            (field["tag"], field["name"], field["type"])
            for field in form["fields"]
        }
        forms.append(
            {
                **{key: value for key, value in form.items() if key != "fields"},
                "fields": [
                    {"tag": tag, "name": name, "type": field_type}
                    for tag, name, field_type in sorted(unique_fields)
                ][:1000],
            }
        )
    return {
        "forms": forms,
        "form_count": len(parser.forms),
        "script_urls": sorted(set(parser.scripts))[:200],
        "inline_script_count": len(parser.inline_scripts),
        "endpoint_candidates": _same_origin_endpoint_candidates(
            parser.scripts,
            parser.inline_scripts,
            search_url,
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--openapi-spec-url",
        default="https://www.lamost.org/openapi/openapi.yaml",
    )
    parser.add_argument(
        "--search-url",
        default="https://www.lamost.org/dr8/v2.0/search",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--maximum-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_public_query_metadata.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    spec_text, spec_receipt = _fetch_text(
        args.openapi_spec_url,
        timeout=args.timeout,
        maximum_bytes=args.maximum_bytes,
    )
    search_text, search_receipt = _fetch_text(
        args.search_url,
        timeout=args.timeout,
        maximum_bytes=args.maximum_bytes,
    )
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "pass",
        "scope": (
            "Public API/search metadata only. No catalogue query, source identifier, "
            "coordinate, spectrum, or radial velocity was submitted or retrieved."
        ),
        "openapi_receipt": spec_receipt,
        "search_receipt": search_receipt,
        "openapi_contract": extract_openapi_contract(spec_text),
        "search_contract": extract_search_contract(search_text, args.search_url),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(args.output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
