#!/usr/bin/env python3
"""Candidate-safe live smoke test for the official Gaia/DESI crossmatch join."""

from __future__ import annotations

import hashlib
import io
import json

import pandas as pd

from hou_compact.datalab import (
    DESI_ZPIX_TABLE,
    GAIA_DESI_XMATCH_TABLE,
    DataLabQueryConfig,
    parse_desi_gaia_overlap_csv,
)
from hou_compact.datalab_query_manager import execute_query_manager_csv


def main() -> None:
    config = DataLabQueryConfig(timeout_seconds=45.0, retries=0)
    discovery_sql = f"""SELECT id2 AS zpix_id
FROM {GAIA_DESI_XMATCH_TABLE}
LIMIT 1"""
    discovery_text, discovery_attempts = execute_query_manager_csv(
        discovery_sql,
        config=config,
    )
    discovery = pd.read_csv(io.StringIO(discovery_text), dtype=str)
    discovery.columns = [str(column).strip().lower() for column in discovery.columns]
    if len(discovery) != 1 or "zpix_id" not in discovery.columns:
        raise RuntimeError(
            "Data Lab discovery smoke did not return exactly one zpix_id row"
        )
    zpix_id = int(discovery.iloc[0]["zpix_id"])

    join_sql = f"""SELECT
    x.id1 AS source_id,
    z.targetid AS targetid,
    z.survey AS survey,
    z.program AS program,
    z.healpix AS healpix,
    x.distance AS match_distance_arcsec
FROM {GAIA_DESI_XMATCH_TABLE} AS x
JOIN {DESI_ZPIX_TABLE} AS z ON x.id2 = z.id
WHERE x.id2 = {zpix_id}
LIMIT 1"""
    text, join_attempts = execute_query_manager_csv(
        join_sql,
        config=config,
    )
    frame = parse_desi_gaia_overlap_csv(text)
    if len(frame) != 1:
        raise RuntimeError(f"schema smoke expected one row, received {len(frame)}")
    payload = {
        "status": "pass",
        "rows": len(frame),
        "columns": frame.columns.tolist(),
        "attempts": discovery_attempts + join_attempts,
        "discovery_query_sha256": hashlib.sha256(
            discovery_sql.encode("utf-8")
        ).hexdigest(),
        "join_query_sha256": hashlib.sha256(join_sql.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "transport": "official_query_manager_nested_query_endpoint",
        "claim_boundary": (
            "No source identifiers or catalogue values are printed by this smoke test."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
