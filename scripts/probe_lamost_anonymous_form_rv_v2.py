#!/usr/bin/env python3
"""Validate anonymous browser-form RV access on a bounded public sample.

The probe chooses up to 25 high-S/N, parameter-bearing public spectra from the
official example cone, submits their coordinates through the live browser form,
and parses the current pipe-delimited response. Row values stay in memory. Only
column names, aggregate counts and request/response hashes are persisted.
"""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import hashlib
import json
from pathlib import Path
import re
from urllib.request import HTTPCookieProcessor, Request, build_opener

import numpy as np
import pandas as pd

from hou_compact.lamost import parse_exact_int_text
from hou_compact.lamost_conesearch import query_lamost_cone
from hou_compact.lamost_form_response import parse_delimited_response, resolve_column
from hou_compact.lamost_search_form import submit_search_form

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
    parser.add_argument("--sample-size", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_anonymous_form_rv_v2_contract.json"),
    )
    return parser.parse_args()


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="strict").strip()
    return str(value).strip()


def _select_samples(frame: pd.DataFrame, sample_size: int) -> pd.DataFrame:
    if sample_size < 1 or sample_size > 100:
        raise ValueError("sample_size must lie in [1, 100]")
    exact = frame["catalogue_gaia_source_id"].map(
        lambda value: re.fullmatch(r"[0-9]+", _text(value)) is not None
    )
    selected = frame.loc[exact].copy()
    if "catalogue_with_norm_flux" in selected.columns:
        normalized = pd.to_numeric(
            selected["catalogue_with_norm_flux"], errors="coerce"
        ).eq(1)
        if normalized.any():
            selected = selected.loc[normalized].copy()
    if "catalogue_class" in selected.columns:
        stellar = selected["catalogue_class"].map(_text).str.upper().eq("STAR")
        if stellar.any():
            selected = selected.loc[stellar].copy()
    if selected.empty:
        raise RuntimeError("example cone contains no exact-identity parameter spectra")
    sn_g = pd.to_numeric(selected.get("catalogue_snrg"), errors="coerce").fillna(-1)
    sn_i = pd.to_numeric(selected.get("catalogue_snri"), errors="coerce").fillna(-1)
    selected["_selection_sn"] = pd.concat([sn_g, sn_i], axis=1).max(axis=1)
    selected = selected.sort_values("_selection_sn", ascending=False, kind="stable")
    return selected.head(sample_size).reset_index(drop=True)


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


def _fields(samples: pd.DataFrame) -> list[tuple[str, object]]:
    lines = ["#ra,dec,sep"]
    for row in samples.itertuples(index=False):
        lines.append(
            f"{float(row.catalogue_ra):.12f},{float(row.catalogue_dec):.12f},2.0"
        )
    fields: list[tuple[str, object]] = [
        ("sForm", "0"),
        ("pos.type", "proximity"),
        ("pos.radecTextarea", "\n".join(lines)),
        ("output.collection", "typical"),
        ("output.fmt", "csv"),
    ]
    fields.extend((f"output.combined.{column}", "on") for column in _OUTPUT_COLUMNS)
    fields.append(("sBtn", "Search"))
    return fields


def _resolve_required(frame: pd.DataFrame) -> dict[str, str]:
    resolved = {column: resolve_column(frame, column) for column in _OUTPUT_COLUMNS}
    required = ("gaia_source_id", "obsid", "mjd", "rv", "rv_err")
    missing = [column for column in required if resolved[column] is None]
    if missing:
        raise RuntimeError(f"anonymous table is missing required columns: {missing}")
    return {key: value for key, value in resolved.items() if value is not None}


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "release": "dr8/v2.0",
        "transport": "same_origin_cookie_multipart_pipe_table",
        "sample_values_persisted": False,
        "response_values_persisted": False,
        "identity_policy": (
            "Position discovers rows; only exact returned Gaia DR3 digit strings present "
            "in the requested sample set count as accepted identities."
        ),
        "claim_boundary": (
            "This is a bounded public transport contract test, not a candidate result or "
            "evidence of variability, binarity or a compact companion."
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
        samples = _select_samples(cone, args.sample_size)
        requested_ids = {
            parse_exact_int_text(value, name="sample.gaia_source_id")
            for value in samples["catalogue_gaia_source_id"]
        }
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        payload["preflight_receipt"] = _preflight(opener, args.search_url, args.timeout)
        body, _, receipt = submit_search_form(
            args.submit_url,
            _fields(samples),
            timeout=args.timeout,
            opener=opener,
            referer=args.search_url,
        )
        frame = parse_delimited_response(body)
        resolved = _resolve_required(frame)
        parsed_ids: list[int | None] = []
        for value in frame[resolved["gaia_source_id"]]:
            try:
                parsed_ids.append(parse_exact_int_text(value, name="result.gaia_source_id"))
            except (TypeError, ValueError):
                parsed_ids.append(None)
        identity = pd.Series(parsed_ids, index=frame.index, dtype="Int64")
        exact_match = identity.isin(requested_ids)
        rv = pd.to_numeric(frame[resolved["rv"]], errors="coerce")
        rv_error = pd.to_numeric(frame[resolved["rv_err"]], errors="coerce")
        finite_pair = exact_match & np.isfinite(rv) & np.isfinite(rv_error) & rv_error.gt(0)
        payload.update(
            {
                "status": "pass" if int(finite_pair.sum()) >= 1 else "no_finite_rv_pair",
                "requested_sample_count": int(len(samples)),
                "returned_row_count": int(len(frame)),
                "returned_columns": sorted(str(column) for column in frame.columns),
                "exact_requested_identity_row_count": int(exact_match.sum()),
                "exact_identity_finite_rv_positive_error_count": int(finite_pair.sum()),
                "form_receipt": receipt.to_record(),
            }
        )
        if payload["status"] != "pass":
            raise RuntimeError(
                "anonymous form returned no exact-identity finite RV/error pair"
            )
    except Exception as error:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:2000]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(args.output.read_text(encoding="utf-8"))
    if payload["status"] != "pass":
        raise RuntimeError(str(payload.get("error", "anonymous RV form probe failed")))


if __name__ == "__main__":
    main()
