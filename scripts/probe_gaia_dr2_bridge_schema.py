#!/usr/bin/env python3
"""Candidate-safe live schema check for Gaia DR3 ``dr2_neighbourhood``."""

from __future__ import annotations

import hashlib
import json

import pyvo

from hou_compact.gaia import DEFAULT_GAIA_TAP_URL


def main() -> None:
    adql = "\n".join(
        [
            "SELECT TOP 1",
            "    d.dr3_source_id AS dr3_source_id,",
            "    d.dr2_source_id AS dr2_source_id,",
            "    d.angular_distance AS angular_distance_mas,",
            "    d.magnitude_difference AS magnitude_difference_mag,",
            "    d.proper_motion_propagation AS proper_motion_propagation",
            "FROM gaiadr3.dr2_neighbourhood AS d",
        ]
    )
    table = pyvo.dal.TAPService(DEFAULT_GAIA_TAP_URL).run_sync(
        adql,
        maxrec=2,
    ).to_table()
    expected = {
        "dr3_source_id",
        "dr2_source_id",
        "angular_distance_mas",
        "magnitude_difference_mag",
        "proper_motion_propagation",
    }
    columns = {str(name).lower() for name in table.colnames}
    if len(table) != 1 or not expected.issubset(columns):
        raise RuntimeError(
            f"Gaia bridge schema smoke failed: rows={len(table)}, columns={sorted(columns)}"
        )
    payload = {
        "status": "pass",
        "rows": len(table),
        "columns": sorted(columns),
        "query_sha256": hashlib.sha256(adql.encode("utf-8")).hexdigest(),
        "claim_boundary": (
            "No Gaia source identifiers or catalogue values are printed by this smoke test."
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
