#!/usr/bin/env python3
"""Probe the public DR8 v2.0 browser search for RV/error output.

One arbitrary public position is discovered through ConeSearch. The browser form
is then submitted in a same-origin cookie session using the exact live defaults.
All row values stay in memory; only column names, aggregate counts, hashes and
fully redacted short protocol diagnostics are persisted.
"""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
import hashlib
from http.cookiejar import CookieJar
from io import BytesIO
import json
import math
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

import numpy as np
import pandas as pd

from hou_compact.lamost_conesearch import query_lamost_cone
from hou_compact.lamost_search_form import (
    LamostSearchFormError,
    submit_search_form,
)

_OUTPUT_COLUMNS = (
    "gaia_source_id",
    "obsid",
    "mjd",
    "rv",
    "rv_err",
    "snrg",
    "snri",
    "snrz",
    "fibermask",
    "class",
    "subclass",
)


class _HTMLContractParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.headers: list[str] = []
        self.paths: set[str] = set()
        self._inside_header = False
        self._chunks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        lowered = tag.lower()
        values = {str(key).lower(): str(value or "") for key, value in attrs}
        if lowered in {"th", "dt"}:
            self._inside_header = True
            self._chunks = []
        for attribute in ("href", "action"):
            raw = values.get(attribute, "").strip()
            if not raw:
                continue
            absolute = urljoin(self.base_url, raw)
            parsed = urlparse(absolute)
            if parsed.netloc == urlparse(self.base_url).netloc:
                self.paths.add(parsed.path or "/")

    def handle_data(self, data: str) -> None:
        if self._inside_header:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"th", "dt"} and self._inside_header:
            text = " ".join("".join(self._chunks).split())
            if text:
                self.headers.append(text[:160])
            self._inside_header = False
            self._chunks = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--search-url",
        default="https://www.lamost.org/dr8/v2.0/search",
    )
    parser.add_argument(
        "--submit-url",
        default="https://www.lamost.org/dr8/v2.0/q",
    )
    parser.add_argument(
        "--conesearch-endpoint",
        default="https://www.lamost.org/dr8/v2.0/voservice/conesearch",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_anonymous_search_submit.json"),
    )
    return parser.parse_args()


def _exact_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="strict").strip()
    return str(value).strip()


def _sample(frame: pd.DataFrame) -> pd.Series:
    exact = frame["catalogue_gaia_source_id"].map(
        lambda value: re.fullmatch(r"[0-9]+", _exact_text(value)) is not None
    )
    selected = frame.loc[exact].copy()
    if selected.empty:
        raise RuntimeError("ConeSearch returned no exact-digit Gaia DR3 identity")
    return selected.iloc[0]


def _preflight(opener: object, url: str, timeout: float) -> dict[str, object]:
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "HOU-COMPACT/0.1 public form preflight"},
    )
    with opener.open(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 200))
        content_type = str(response.headers.get("Content-Type", ""))
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise RuntimeError("search preflight exceeded the byte limit")
    if status != 200:
        raise RuntimeError(f"search preflight returned HTTP {status}")
    return {
        "status": status,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _fields(row: pd.Series) -> list[tuple[str, object]]:
    ra = float(pd.to_numeric(row["catalogue_ra"], errors="raise"))
    dec = float(pd.to_numeric(row["catalogue_dec"], errors="raise"))
    fields: list[tuple[str, object]] = [
        ("sForm", "0"),
        ("pos.type", "proximity"),
        ("pos.radecTextarea", f"#ra,dec,sep\n{ra:.12f},{dec:.12f},2.0"),
        ("output.collection", "typical"),
        ("output.fmt", "csv"),
    ]
    fields.extend((f"output.combined.{column}", "on") for column in _OUTPUT_COLUMNS)
    fields.append(("sBtn", "Search"))
    return fields


def _resolve(frame: pd.DataFrame, wanted: str) -> str | None:
    normalized = {
        str(column).strip().lower().replace(" ", "_"): str(column)
        for column in frame.columns
    }
    for candidate in (
        wanted,
        f"combined.{wanted}",
        f"combined_{wanted}",
        f"catalogue_{wanted}",
    ):
        if candidate in normalized:
            return normalized[candidate]
    suffix_matches = [
        original
        for normalized_name, original in normalized.items()
        if normalized_name.endswith(f".{wanted}")
        or normalized_name.endswith(f"_{wanted}")
    ]
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def _csv_contract(body: bytes) -> dict[str, object]:
    frame = pd.read_csv(BytesIO(body), dtype="string")
    resolved = {name: _resolve(frame, name) for name in _OUTPUT_COLUMNS}
    required = ("gaia_source_id", "obsid", "mjd", "rv", "rv_err")
    missing = [name for name in required if resolved[name] is None]
    payload: dict[str, object] = {
        "result_row_count": int(len(frame)),
        "returned_columns": sorted(str(column) for column in frame.columns),
        "missing_required_columns": missing,
    }
    if missing:
        return payload
    identity = frame[resolved["gaia_source_id"]].astype("string").str.strip()
    rv = pd.to_numeric(frame[resolved["rv"]], errors="coerce")
    rv_error = pd.to_numeric(frame[resolved["rv_err"]], errors="coerce")
    payload.update(
        {
            "exact_digit_identity_rows": int(identity.str.fullmatch(r"[0-9]+").sum()),
            "finite_rv_rows": int(np.isfinite(rv).sum()),
            "finite_positive_rv_error_rows": int(
                (np.isfinite(rv_error) & rv_error.gt(0)).sum()
            ),
            "finite_rv_with_positive_error_rows": int(
                (np.isfinite(rv) & np.isfinite(rv_error) & rv_error.gt(0)).sum()
            ),
        }
    )
    return payload


def _sanitized_text(body: bytes) -> str | None:
    if len(body) > 4096:
        return None
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if not text:
        return ""
    printable = sum(character.isprintable() or character.isspace() for character in text)
    if printable / len(text) < 0.9:
        return None
    text = " ".join(text.split())
    text = re.sub(r"https?://\S+", "[url-redacted]", text)
    text = re.sub(r"[A-Za-z0-9_-]{24,}", "[token-redacted]", text)
    text = re.sub(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", "[number-redacted]", text)
    return text[:1000]


def _non_csv_contract(body: bytes, final_url: str) -> dict[str, object]:
    printable = 0.0
    if body:
        printable = sum(32 <= value <= 126 or value in {9, 10, 13} for value in body) / len(body)
    payload: dict[str, object] = {
        "magic_hex": body[:24].hex(),
        "printable_fraction": round(printable, 6),
        "final_path": urlparse(final_url).path or "/",
    }
    sanitized = _sanitized_text(body)
    if sanitized is not None:
        payload["sanitized_text"] = sanitized
    if body[:2] == b"\x1f\x8b":
        payload["binary_signature"] = "gzip"
    elif body[:4] == b"PK\x03\x04":
        payload["binary_signature"] = "zip"
    elif body[:6] == b"SIMPLE":
        payload["binary_signature"] = "fits"
    return payload


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.2",
        "candidate_safe": True,
        "status": "failure",
        "transport": "same_origin_cookie_multipart_form",
        "release": "dr8/v2.0",
        "form_defaults": {
            "sForm": "0",
            "pos.type": "proximity",
            "output.collection": "typical",
            "output.fmt": "csv",
            "checkbox_value": "on",
        },
        "request_values_persisted": False,
        "result_values_persisted": False,
        "claim_boundary": (
            "One arbitrary public position is used only to validate anonymous browser-form "
            "access to exact identity, epoch, RV and RV uncertainty columns."
        ),
    }
    try:
        cone, _ = query_lamost_cone(
            args.conesearch_endpoint,
            ra_deg=10.0004738,
            dec_deg=40.9952444,
            radius_deg=0.2,
            timeout=args.timeout,
        )
        row = _sample(cone)
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        payload["preflight_receipt"] = _preflight(opener, args.search_url, args.timeout)
        body, final_url, receipt = submit_search_form(
            args.submit_url,
            _fields(row),
            timeout=args.timeout,
            opener=opener,
            referer=args.search_url,
        )
        payload["form_receipt"] = receipt.to_record()
        if receipt.response_kind == "csv" or b"," in body[:1024]:
            contract = _csv_contract(body)
            payload["csv_contract"] = contract
            if contract["missing_required_columns"]:
                raise RuntimeError(
                    "anonymous form CSV is missing required RV contract columns"
                )
            if int(contract["finite_rv_with_positive_error_rows"]) < 1:
                raise RuntimeError(
                    "anonymous form CSV contains no finite RV with positive uncertainty"
                )
            if int(contract["exact_digit_identity_rows"]) < 1:
                raise RuntimeError(
                    "anonymous form CSV contains no exact-digit Gaia DR3 identity"
                )
            payload["status"] = "pass"
        else:
            parser = _HTMLContractParser(final_url)
            parser.feed(body.decode("utf-8", errors="replace"))
            payload["html_contract"] = {
                "headers": sorted(set(parser.headers))[:200],
                "same_origin_paths": sorted(parser.paths)[:200],
            }
            payload["non_csv_contract"] = _non_csv_contract(body, final_url)
            raise RuntimeError(
                f"anonymous form returned {receipt.response_kind} instead of CSV"
            )
    except Exception as error:
        if isinstance(error, LamostSearchFormError) and error.receipt is not None:
            payload["form_failure_receipt"] = error.receipt.to_record()
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:2000]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(args.output.read_text(encoding="utf-8"))
    if payload["status"] != "pass":
        raise RuntimeError(str(payload.get("error", "anonymous form contract failed")))


if __name__ == "__main__":
    main()
