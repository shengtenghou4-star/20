#!/usr/bin/env python3
"""Probe anonymous LAMOST ConeSearch-to-combined-table RV access.

One arbitrary public spectrum is discovered through ConeSearch, then its exact
``obsid`` is submitted to the documented ``combined`` TableQuery endpoint using
the official pylamost JSON contract. Row values and request bodies stay in memory;
only candidate-safe response metadata is persisted.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from hou_compact.lamost_conesearch import query_lamost_cone
from hou_compact.lamost_table_query import (
    LamostTableQueryError,
    post_table_query,
)

_REQUIRED_CONE_COLUMNS = {
    "catalogue_gaia_source_id",
    "catalogue_obsid",
    "catalogue_ra",
    "catalogue_dec",
}
_REQUIRED_QUERY_COLUMNS = {"obsid", "rv", "rv_err"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi-root", default="https://www.lamost.org/openapi")
    parser.add_argument(
        "--conesearch-endpoint",
        default="https://www.lamost.org/dr8/v2.0/voservice/conesearch",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_anonymous_table_query_contract.json"),
    )
    return parser.parse_args()


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(path.read_text(encoding="utf-8"))


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="strict").strip()
    return str(value).strip()


def _select_sample(frame: pd.DataFrame) -> pd.Series:
    exact_identity = frame["catalogue_gaia_source_id"].map(
        lambda value: re.fullmatch(r"[0-9]+", _text(value)) is not None
    )
    selected = frame.loc[exact_identity].copy()
    if selected.empty:
        raise RuntimeError("ConeSearch returned no exact-digit Gaia DR3 identity")
    if "catalogue_with_norm_flux" in selected.columns:
        normalized = pd.to_numeric(
            selected["catalogue_with_norm_flux"], errors="coerce"
        ).eq(1)
        if normalized.any():
            selected = selected.loc[normalized].copy()
    return selected.iloc[0]


def _official_query_body(sample: pd.Series) -> dict[str, object]:
    obsid = int(pd.to_numeric(sample["catalogue_obsid"], errors="raise"))
    ra = float(pd.to_numeric(sample["catalogue_ra"], errors="raise"))
    dec = float(pd.to_numeric(sample["catalogue_dec"], errors="raise"))
    return {
        "column_constraints": [
            {
                "column_name": "obsid",
                "constraint": str(obsid),
                "operation": "equal",
            }
        ],
        "order": "asc",
        "output.fmt": "json",
        "page": 1,
        "pos": {
            "proximity": {
                "defaultRadius": 2,
                "proximity_nearestonly": False,
                "radecTextarea": f"{ra:.12f},{dec:.12f},2.0",
            }
        },
        "pos_group": "ra,dec",
        "rows": 5,
        "showcol": ["obsid", "rv", "rv_err"],
        "sort": "obsid",
    }


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "release": "dr8/v2.0",
        "transport": "anonymous_conesearch_plus_table_query_post",
        "table_name": "combined",
        "official_request_shape": {
            "column_constraints": True,
            "order": True,
            "output.fmt": True,
            "page": True,
            "pos": True,
            "pos_group": True,
            "rows": True,
            "showcol": True,
            "sort": True,
        },
        "row_values_persisted": False,
        "request_body_persisted": False,
        "claim_boundary": (
            "One arbitrary public spectrum is used only to validate anonymous access to "
            "obsid, rv, and rv_err. No identifier, coordinate, request body, or row value "
            "is persisted."
        ),
    }
    try:
        cone, cone_receipt = query_lamost_cone(
            args.conesearch_endpoint,
            ra_deg=10.0004738,
            dec_deg=40.9952444,
            radius_deg=0.2,
            timeout=args.timeout,
        )
        returned_cone = {str(column).lower() for column in cone.columns}
        missing_cone = sorted(_REQUIRED_CONE_COLUMNS - returned_cone)
        payload.update(
            {
                "cone_row_count": int(len(cone)),
                "cone_returned_columns": sorted(returned_cone),
                "cone_missing_columns": missing_cone,
                "cone_receipt": cone_receipt.to_record(),
            }
        )
        if missing_cone:
            raise RuntimeError(f"ConeSearch missing columns: {missing_cone}")
        sample = _select_sample(cone)
        query_body = _official_query_body(sample)
        rows, table_receipt = post_table_query(
            args.openapi_root,
            dr_version="dr8",
            sub_version="v2.0",
            table_name="combined",
            query=query_body,
            timeout=args.timeout,
        )
        returned_query = {str(column).lower() for column in rows.columns}
        missing_query = sorted(_REQUIRED_QUERY_COLUMNS - returned_query)
        payload.update(
            {
                "table_query_receipt": table_receipt.to_record(),
                "table_query_returned_columns": sorted(returned_query),
                "table_query_missing_columns": missing_query,
                "table_query_row_count": int(len(rows)),
            }
        )
        if missing_query:
            raise RuntimeError(f"combined TableQuery missing columns: {missing_query}")
        if rows.empty:
            raise RuntimeError("combined TableQuery returned no row for exact obsid")
        rv = pd.to_numeric(rows["rv"], errors="coerce")
        rv_error = pd.to_numeric(rows["rv_err"], errors="coerce")
        valid = rv.notna() & rv_error.notna() & rv_error.gt(0)
        if not valid.any():
            raise RuntimeError(
                "combined TableQuery returned no finite RV with positive uncertainty"
            )
        payload.update(
            {
                "status": "pass",
                "finite_rv_with_positive_error_present": True,
            }
        )
        _write(args.output, payload)
    except Exception as error:
        if isinstance(error, LamostTableQueryError) and error.receipt is not None:
            payload["table_query_failure_receipt"] = error.receipt.to_record()
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:2000]
        _write(args.output, payload)
        raise


if __name__ == "__main__":
    main()
