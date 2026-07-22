#!/usr/bin/env python3
"""Probe the public LAMOST catalogue-search HTML contract without candidate data.

The probe records form actions and control names needed to build a bounded exact-
obsid query client. Hidden values and free-text defaults are never persisted, so
session/CSRF material and example identifiers cannot leak into the public artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

_SAFE_ATTRIBUTE = re.compile(r"^[A-Za-z0-9_./:+-]{0,200}$")
_SENSITIVE_NAME = re.compile(r"csrf|token|session|auth|secret|password", re.IGNORECASE)


class SearchFormParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.forms: list[dict[str, Any]] = []
        self.current_form: dict[str, Any] | None = None
        self.current_select: dict[str, Any] | None = None
        self.current_textarea: dict[str, Any] | None = None

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).lower(): "" if value is None else str(value) for key, value in attrs}

    @staticmethod
    def _safe_literal(value: str, *, name: str) -> str | None:
        if not value or _SENSITIVE_NAME.search(name):
            return None
        if _SAFE_ATTRIBUTE.fullmatch(value):
            return value
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = self._attrs(attrs)
        tag = tag.lower()
        if tag == "form":
            if self.current_form is not None:
                raise RuntimeError("nested HTML forms are not supported")
            action = attributes.get("action", "")
            self.current_form = {
                "action": urljoin(self.base_url, action),
                "method": attributes.get("method", "get").lower(),
                "enctype": attributes.get("enctype", "application/x-www-form-urlencoded"),
                "id": attributes.get("id", ""),
                "name": attributes.get("name", ""),
                "controls": [],
            }
            return
        if self.current_form is None:
            return
        if tag in {"input", "button"}:
            name = attributes.get("name", "")
            value = attributes.get("value", "")
            control_type = attributes.get("type", "text" if tag == "input" else "submit").lower()
            self.current_form["controls"].append(
                {
                    "tag": tag,
                    "type": control_type,
                    "name": name,
                    "id": attributes.get("id", ""),
                    "checked": "checked" in attributes,
                    "disabled": "disabled" in attributes,
                    "safe_value": self._safe_literal(value, name=name),
                    "value_present": bool(value),
                    "value_length": len(value),
                }
            )
        elif tag == "select":
            self.current_select = {
                "tag": "select",
                "type": "select",
                "name": attributes.get("name", ""),
                "id": attributes.get("id", ""),
                "multiple": "multiple" in attributes,
                "options": [],
            }
            self.current_form["controls"].append(self.current_select)
        elif tag == "option" and self.current_select is not None:
            name = str(self.current_select.get("name", ""))
            value = attributes.get("value", "")
            self.current_select["options"].append(
                {
                    "safe_value": self._safe_literal(value, name=name),
                    "value_present": bool(value),
                    "selected": "selected" in attributes,
                }
            )
        elif tag == "textarea":
            self.current_textarea = {
                "tag": "textarea",
                "type": "textarea",
                "name": attributes.get("name", ""),
                "id": attributes.get("id", ""),
                "default_length": 0,
                "default_sha256": None,
            }
            self.current_form["controls"].append(self.current_textarea)

    def handle_data(self, data: str) -> None:
        if self.current_textarea is None:
            return
        prior = str(self.current_textarea.get("_raw_default", ""))
        self.current_textarea["_raw_default"] = prior + data

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "select":
            self.current_select = None
        elif tag == "textarea" and self.current_textarea is not None:
            raw = str(self.current_textarea.pop("_raw_default", ""))
            self.current_textarea["default_length"] = len(raw)
            self.current_textarea["default_sha256"] = (
                hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None
            )
            self.current_textarea = None
        elif tag == "form" and self.current_form is not None:
            self.forms.append(self.current_form)
            self.current_form = None
            self.current_select = None
            self.current_textarea = None


def _control_key(control: dict[str, Any]) -> str:
    return " ".join(
        str(control.get(field, "")).lower() for field in ("name", "id", "type", "tag")
    )


def probe(url: str, output: Path, *, timeout: float = 120.0) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise ValueError("url must use HTTPS")
    request = Request(
        url,
        headers={
            "User-Agent": "HOU-COMPACT/0.4 LAMOST form-contract probe",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        final_url = str(getattr(response, "geturl", lambda: url)())
        content_type = str(response.headers.get("Content-Type", ""))
        raw = response.read(8 * 1024 * 1024 + 1)
    if status != 200:
        raise RuntimeError(f"LAMOST search page returned HTTP {status}")
    if len(raw) > 8 * 1024 * 1024:
        raise RuntimeError("LAMOST search page exceeded eight MiB")
    text = raw.decode("utf-8-sig", errors="strict")
    parser = SearchFormParser(final_url)
    parser.feed(text)
    parser.close()
    if not parser.forms:
        raise RuntimeError("LAMOST search page exposes no HTML form")

    likely_obsid: list[dict[str, Any]] = []
    likely_output: list[dict[str, Any]] = []
    for form_index, form in enumerate(parser.forms):
        for control_index, control in enumerate(form["controls"]):
            key = _control_key(control)
            reference = {
                "form_index": form_index,
                "control_index": control_index,
                "name": control.get("name", ""),
                "id": control.get("id", ""),
                "type": control.get("type", ""),
            }
            if "obsid" in key or ("obs" in key and "id" in key):
                likely_obsid.append(reference)
            if any(token in key for token in ("format", "output", "return", "column", "field")):
                likely_output.append(reference)

    payload: dict[str, Any] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "html_bytes": len(raw),
        "html_sha256": hashlib.sha256(raw).hexdigest(),
        "form_count": len(parser.forms),
        "forms": parser.forms,
        "likely_obsid_controls": likely_obsid,
        "likely_output_controls": likely_output,
        "claim_boundary": (
            "This artifact records public HTML form metadata only. It submits no obsid, "
            "source identifier, candidate coordinate, or radial-velocity value."
        ),
    }
    if not likely_obsid:
        raise RuntimeError("no likely obsid form control was discovered")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="https://www.lamost.org/dr8/v1.0/search",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("lamost_search_form_contract.json"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = probe(args.url, args.output, timeout=args.timeout)
    safe = {
        "status": "success",
        "form_count": payload["form_count"],
        "likely_obsid_controls": payload["likely_obsid_controls"],
        "likely_output_control_count": len(payload["likely_output_controls"]),
        "candidate_safe": True,
    }
    print(json.dumps(safe, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
