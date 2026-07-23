#!/usr/bin/env python3
"""Validate one public APOGEE DR17 star-to-visit join.

The probe runs a bounded anonymous SkyServer query returning one arbitrary
quality-controlled visit.  No Gaia ID, visit ID, time, velocity, uncertainty,
telescope, survey, or target value is persisted.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

from hou_compact.apogee_dr17 import build_sample_query
from hou_compact.lamost import parse_exact_int_text
from hou_compact.skyserver_sql import SkyServerSQLError, skyserver_sql_get


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        default=(
            "https://skyserver.sdss.org/dr17/"
            "SkyServerWS/SearchTools/SqlSearch"
        ),
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/apogee_dr17_visit_contract.json"),
    )
    return parser.parse_args()


def _column(frame: pd.DataFrame, wanted: str) -> str:
    mapping = {str(column).strip().lower(): str(column) for column in frame.columns}
    if wanted.lower() not in mapping:
        raise RuntimeError(f"APOGEE sample is missing {wanted}")
    return mapping[wanted.lower()]


def main() -> None:
    args = parse_args()
    payload: dict[str, object] = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "status": "failure",
        "release": "SDSS DR17 APOGEE-2",
        "transport": "anonymous_skyserver_exact_star_visit_join",
        "sample_values_persisted": False,
        "quality_contract": "finite MJD/VHELIO/positive VRELERR, SNR>20, STARFLAG=0",
        "claim_boundary": (
            "This probe validates one arbitrary public exact star-to-visit join only. It "
            "is not a Dark-668 overlap, variability, binary, compact-object, or novelty "
            "result."
        ),
    }
    try:
        frame, receipt = skyserver_sql_get(
            args.endpoint,
            build_sample_query(),
            maximum_rows=1,
            timeout=args.timeout,
        )
        if len(frame) != 1:
            raise RuntimeError("APOGEE sample query did not return exactly one row")
        row = frame.iloc[0]
        parse_exact_int_text(
            row[_column(frame, "gaiaedr3_source_id")],
            name="apogee.gaiaedr3_source_id",
        )
        visit_id = str(row[_column(frame, "visit_id")]).strip()
        if not visit_id:
            raise RuntimeError("APOGEE sample visit_id is empty")
        mjd = float(pd.to_numeric(row[_column(frame, "mjd")], errors="raise"))
        jd = float(pd.to_numeric(row[_column(frame, "jd")], errors="raise"))
        rv = float(pd.to_numeric(row[_column(frame, "vhelio")], errors="raise"))
        rv_error = float(
            pd.to_numeric(row[_column(frame, "vrelerr")], errors="raise")
        )
        snr = float(pd.to_numeric(row[_column(frame, "snr")], errors="raise"))
        starflag = int(
            pd.to_numeric(row[_column(frame, "starflag")], errors="raise")
        )
        if not math.isfinite(mjd) or not math.isfinite(jd):
            raise RuntimeError("APOGEE sample visit time is not finite")
        if not math.isfinite(rv):
            raise RuntimeError("APOGEE sample VHELIO is not finite")
        if not math.isfinite(rv_error) or rv_error <= 0:
            raise RuntimeError("APOGEE sample VRELERR is not finite and positive")
        if snr <= 20 or starflag != 0:
            raise RuntimeError("APOGEE sample does not pass the frozen quality gate")
        payload.update(
            {
                "status": "pass",
                "sample_row_count": 1,
                "sample_has_exact_gaia_identity": True,
                "sample_has_visit_id": True,
                "sample_has_finite_time_rv_positive_error": True,
                "sample_passes_quality_gate": True,
                "returned_columns": sorted(str(column) for column in frame.columns),
                "sql_receipt": receipt.to_record(),
            }
        )
    except (SkyServerSQLError, KeyError, TypeError, ValueError, RuntimeError) as error:
        payload["error_type"] = type(error).__name__
        payload["error"] = str(error)[:1000]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(args.output.read_text(encoding="utf-8"))
    if payload["status"] != "pass":
        raise RuntimeError(str(payload.get("error", "APOGEE visit contract failed")))


if __name__ == "__main__":
    main()
