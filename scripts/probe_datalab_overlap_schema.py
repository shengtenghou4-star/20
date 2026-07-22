#!/usr/bin/env python3
"""Candidate-safe live smoke test for the official Gaia/DESI crossmatch join."""

from __future__ import annotations

import hashlib
import json

from hou_compact.datalab import (
    DESI_ZPIX_TABLE,
    GAIA_DESI_XMATCH_TABLE,
    DataLabQueryConfig,
    execute_sync_csv_query,
    parse_desi_gaia_overlap_csv,
)


def main() -> None:
    sql = f"""SELECT TOP 1
    x.id1 AS source_id,
    z.targetid AS targetid,
    z.survey AS survey,
    z.program AS program,
    z.healpix AS healpix,
    x.distance AS match_distance_arcsec
FROM {GAIA_DESI_XMATCH_TABLE} AS x
JOIN {DESI_ZPIX_TABLE} AS z ON x.id2 = z.id
WHERE z.survey = 'main'
  AND z.program IN ('bright','dark')"""
    text, attempts = execute_sync_csv_query(
        sql,
        config=DataLabQueryConfig(timeout_seconds=120.0, retries=2),
    )
    frame = parse_desi_gaia_overlap_csv(text)
    if len(frame) != 1:
        raise RuntimeError(f"schema smoke expected one row, received {len(frame)}")
    payload = {
        "status": "pass",
        "rows": len(frame),
        "columns": frame.columns.tolist(),
        "attempts": attempts,
        "query_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "claim_boundary": (
            "No source identifiers or catalogue values are printed by this smoke test."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
