#!/usr/bin/env python3
"""Validate anonymous LAMOST RV access through native Gaia DR3 ID constraints.

The probe discovers a bounded public sample through the official ConeSearch,
then resubmits only the exact Gaia DR3 identifiers through ``gaiasourcearea``
with no positional constraint.  Row values remain in memory; the persisted
receipt contains aggregate counts, schema names and hashes only.
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
from hou_compact.lamost_gaia_id_form import (
    build_gaia_id_form_fields,
    normalize_form_table,
)
from hou_compact.lamost_search_form import submit_search_form


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
        default=Path("outputs/lamost_gaia_id_form_contract.json"),
    )
    return parser.parse_args()


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="strict").strip()
    return str(value).strip()


def _select_ids(frame: pd.DataFrame, sample_size: int) -> list[int]:
    if sample_size < 1 or sample_size > 100:
        raise ValueError("sample_size must lie in [1, 100]")
    exact = frame["catalogue_gaia_source_id"].map(
        lambda value: re.fullmatch(r"[0-9]+", _text(value)) is not None
    )
    selected = frame.loc[exact].copy()
    if "catalogue_with_norm_flux" in selected.columns:
        parameterized = pd.to_numeric(
            selected["catalogue_with_norm_flux"], errors="coerce"
        ).eq(1)
        if parameterized.any():
            selected = selected.loc[parameterized].copy()
    if "catalogue_class" in selected.columns:
        stellar = selected["catalogue_class"].map(_text).str.upper().eq("STAR")
        if stellar.any():
            selected = selected.loc[stellar].copy()
    if selected.empty:
        raise RuntimeError("example cone contains no exact Gaia DR3 identities")
    sn_g = pd.to_numeric(selected.get("catalogue_snrg"), errors="coerce").fillna(-1)
    sn_i = pd.to_numeric(selected.get("catalogue_snri"), errors="coerce").fillna(-1)
    selected["_selection_sn"] = pd.concat([sn_g, sn_i], axis=1).max(axis=1)
    selected = selected.sort_values("_selection_sn", ascending=False, kind="stable")
    values = [
        parse_exact_int_text(value, name="sample.gaia_source_id")
        for value in selected["catalogue_gaia_source_id"].head(sample_size)
    ]
    return list(dict.fromkeys(values))


def _preflight(opener: object, url: str, timeout: float) -> dict[str, object]:
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": "HOU-COMPACT/0.1 Gaia-ID form preflight"},
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


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "release": "dr8/v2.0",
        "transport": "same_origin_cookie_multipart_native_gaia_id_list",
        "sample_values_persisted": False,
        "response_values_persisted": False,
        "identity_policy": (
            "The request uses native Gaia DR3 ID constraints and returned rows count only "
            "when their exact digit-string identity belongs to the submitted set."
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
        requested_ids = _select_ids(cone, args.sample_size)
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        payload["preflight_receipt"] = _preflight(opener, args.search_url, args.timeout)
        body, _, receipt = submit_search_form(
            args.submit_url,
            build_gaia_id_form_fields(requested_ids),
            timeout=args.timeout,
            opener=opener,
            referer=args.search_url,
        )
        frame = normalize_form_table(body)
        parsed_ids: list[int | None] = []
        for value in frame["gaia_source_id"]:
            try:
                parsed_ids.append(
                    parse_exact_int_text(value, name="result.gaia_source_id")
                )
            except (TypeError, ValueError):
                parsed_ids.append(None)
        identity = pd.Series(parsed_ids, index=frame.index, dtype="Int64")
        exact_match = identity.isin(set(requested_ids))
        rv = pd.to_numeric(frame["rv"], errors="coerce")
        rv_error = pd.to_numeric(frame["rv_err"], errors="coerce")
        finite_pair = exact_match & np.isfinite(rv) & np.isfinite(rv_error) & rv_error.gt(0)
        payload.update(
            {
                "status": "pass" if int(finite_pair.sum()) >= 1 else "no_finite_rv_pair",
                "requested_sample_count": len(requested_ids),
                "returned_row_count": len(frame),
                "returned_columns": sorted(str(column) for column in frame.columns),
                "exact_requested_identity_row_count": int(exact_match.sum()),
                "exact_identity_finite_rv_positive_error_count": int(finite_pair.sum()),
                "form_receipt": receipt.to_record(),
            }
        )
        if payload["status"] != "pass":
            raise RuntimeError(
                "native Gaia-ID form returned no exact finite RV/error pair"
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
        raise RuntimeError(str(payload.get("error", "Gaia-ID form probe failed")))


if __name__ == "__main__":
    main()
