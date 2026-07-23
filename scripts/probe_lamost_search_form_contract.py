#!/usr/bin/env python3
"""Extract the public LAMOST search form defaults and submission logic.

Only the official DR8 v2.0 search HTML and its same-origin JavaScript are fetched.
The probe persists form actions, selected defaults, relevant control attributes,
script hashes, and bounded snippets around submission keywords. It never submits a
search or sends a source identifier, coordinate, spectrum, or radial velocity.
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


_RELEVANT_NAMES = {
    "sForm",
    "sBtn",
    "pos.type",
    "pos.radecTextarea",
    "pos.radius",
    "output.collection",
    "output.fmt",
    "output.combined.gaia_source_id",
    "output.combined.obsid",
    "output.combined.mjd",
    "output.combined.rv",
    "output.combined.rv_err",
    "output.combined.snrg",
    "output.combined.snri",
    "output.combined.snrz",
    "output.combined.fibermask",
    "output.combined.class",
    "output.combined.subclass",
}
_KEYWORDS = (
    "sform",
    "sbtn",
    "formdata",
    "serialize",
    "submit",
    "output.fmt",
    "output.collection",
    "/q",
    "ajax",
    "multipart",
    "radectextarea",
)


class SearchFormParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.forms: list[dict[str, Any]] = []
        self.scripts: list[str] = []
        self._current_form: dict[str, Any] | None = None
        self._current_select: dict[str, Any] | None = None
        self._current_option: dict[str, Any] | None = None
        self._current_textarea: dict[str, Any] | None = None
        self._text_chunks: list[str] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).lower(): str(value or "") for key, value in attrs}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.lower()
        values = self._attrs(attrs)
        if lowered == "form":
            form = {
                "action": urljoin(self.base_url, values.get("action", "")),
                "method": values.get("method", "get").lower(),
                "enctype": values.get("enctype", ""),
                "id": values.get("id", ""),
                "name": values.get("name", ""),
                "controls": [],
            }
            self.forms.append(form)
            self._current_form = form
            return
        if lowered == "script":
            source = values.get("src", "").strip()
            if source:
                self.scripts.append(urljoin(self.base_url, source))
            return
        if self._current_form is None:
            return
        if lowered == "input":
            name = values.get("name", "").strip()
            control_type = values.get("type", "text").lower()
            checked = "checked" in values
            if name in _RELEVANT_NAMES or control_type in {"hidden", "radio", "submit"} or checked:
                self._current_form["controls"].append(
                    {
                        "tag": "input",
                        "name": name,
                        "type": control_type,
                        "value": values.get("value", ""),
                        "checked": checked,
                        "disabled": "disabled" in values,
                    }
                )
        elif lowered == "select":
            name = values.get("name", "").strip()
            control = {
                "tag": "select",
                "name": name,
                "multiple": "multiple" in values,
                "disabled": "disabled" in values,
                "options": [],
            }
            self._current_form["controls"].append(control)
            self._current_select = control
        elif lowered == "option" and self._current_select is not None:
            option = {
                "value": values.get("value", ""),
                "selected": "selected" in values,
                "disabled": "disabled" in values,
                "text": "",
            }
            self._current_select["options"].append(option)
            self._current_option = option
            self._text_chunks = []
        elif lowered == "textarea":
            name = values.get("name", "").strip()
            control = {
                "tag": "textarea",
                "name": name,
                "disabled": "disabled" in values,
                "value": "",
            }
            if name in _RELEVANT_NAMES:
                self._current_form["controls"].append(control)
                self._current_textarea = control
                self._text_chunks = []

    def handle_data(self, data: str) -> None:
        if self._current_option is not None or self._current_textarea is not None:
            self._text_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "option" and self._current_option is not None:
            self._current_option["text"] = "".join(self._text_chunks).strip()
            if not self._current_option["value"]:
                self._current_option["value"] = self._current_option["text"]
            self._current_option = None
            self._text_chunks = []
        elif lowered == "select":
            self._current_select = None
            self._current_option = None
            self._text_chunks = []
        elif lowered == "textarea" and self._current_textarea is not None:
            self._current_textarea["value"] = "".join(self._text_chunks)
            self._current_textarea = None
            self._text_chunks = []
        elif lowered == "form":
            self._current_form = None


def fetch_text(
    url: str,
    *,
    timeout: float,
    maximum_bytes: int,
) -> tuple[str, dict[str, object]]:
    request = Request(
        url,
        method="GET",
        headers={
            "User-Agent": "HOU-COMPACT/0.1 public form-contract probe",
            "Accept": "text/html,application/javascript,text/javascript,*/*;q=0.1",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        content_type = str(response.headers.get("Content-Type", ""))
        body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise RuntimeError("public form metadata exceeded the byte limit")
    if status != 200:
        raise RuntimeError(f"public form metadata returned HTTP {status}")
    return body.decode("utf-8-sig", errors="replace"), {
        "url": url,
        "status": status,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def extract_keyword_snippets(
    text: str,
    *,
    keywords: tuple[str, ...] = _KEYWORDS,
    radius: int = 320,
    maximum_snippets: int = 120,
) -> list[dict[str, str]]:
    compact = re.sub(r"\s+", " ", text)
    lowered = compact.lower()
    snippets: list[dict[str, str]] = []
    seen: set[str] = set()
    for keyword in keywords:
        start = 0
        while len(snippets) < maximum_snippets:
            index = lowered.find(keyword.lower(), start)
            if index < 0:
                break
            left = max(0, index - radius)
            right = min(len(compact), index + len(keyword) + radius)
            snippet = compact[left:right]
            digest = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
            if digest not in seen:
                seen.add(digest)
                snippets.append({"keyword": keyword, "snippet": snippet})
            start = index + len(keyword)
    return snippets


def extract_form_contract(html_text: str, search_url: str) -> dict[str, object]:
    parser = SearchFormParser(search_url)
    parser.feed(html_text)
    forms = []
    for form in parser.forms:
        controls = []
        for control in form["controls"]:
            if control["tag"] == "select":
                options = control["options"]
                selected = [option for option in options if option["selected"]]
                controls.append(
                    {
                        **{key: value for key, value in control.items() if key != "options"},
                        "selected_options": selected,
                        "option_count": len(options),
                        "options": options[:100],
                    }
                )
            else:
                controls.append(control)
        forms.append(
            {
                **{key: value for key, value in form.items() if key != "controls"},
                "controls": controls,
            }
        )
    return {
        "forms": forms,
        "form_count": len(forms),
        "script_urls": sorted(set(parser.scripts)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--search-url",
        default="https://www.lamost.org/dr8/v2.0/search",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--maximum-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_search_form_contract.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    html_text, html_receipt = fetch_text(
        args.search_url,
        timeout=args.timeout,
        maximum_bytes=args.maximum_bytes,
    )
    contract = extract_form_contract(html_text, args.search_url)
    origin = urlparse(args.search_url).netloc
    scripts: list[dict[str, object]] = []
    for script_url in contract["script_urls"]:
        parsed = urlparse(str(script_url))
        if parsed.netloc != origin:
            continue
        if not any(
            token in parsed.path.lower()
            for token in ("combined-search", "lamost.js")
        ):
            continue
        script_text, receipt = fetch_text(
            str(script_url),
            timeout=args.timeout,
            maximum_bytes=args.maximum_bytes,
        )
        scripts.append(
            {
                "receipt": receipt,
                "snippets": extract_keyword_snippets(script_text),
            }
        )
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "pass",
        "scope": (
            "Public search-form and JavaScript metadata only. No search was submitted "
            "and no source identifier, coordinate, spectrum, or RV was retrieved."
        ),
        "html_receipt": html_receipt,
        "form_contract": contract,
        "script_contracts": scripts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(args.output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
