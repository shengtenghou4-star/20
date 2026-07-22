"""TAP-compatible Gaia DR3-to-DR2 bridge retrieval.

Gaia's TAP parser rejects scalar expressions such as ``ABS(...)`` in this
``ORDER BY`` context.  The server query therefore orders only by plain columns;
HOU-COMPACT applies the absolute-magnitude tie-break deterministically after the
complete bounded response has been validated.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable

import pandas as pd

from hou_compact.gaia_dr2_bridge import (
    GaiaDr2BridgeBatchReceipt,
    GaiaDr2BridgeConfig,
    GaiaDr2BridgeError,
    _default_query_executor,
    _source_ids,
    _validate_batch,
)

_EXPECTED_COLUMNS = (
    "dr3_source_id",
    "dr2_source_id",
    "angular_distance_mas",
    "magnitude_difference_mag",
    "proper_motion_propagation",
)


def build_gaia_dr2_bridge_adql_v2(source_ids: Iterable[int]) -> str:
    """Build a Gaia TAP query using only parser-safe ORDER BY columns."""
    identifiers = _source_ids(source_ids)
    if not identifiers:
        raise ValueError("source_ids must not be empty")
    values = ",".join(str(value) for value in identifiers)
    return "\n".join(
        [
            "SELECT",
            "    d.dr3_source_id AS dr3_source_id,",
            "    d.dr2_source_id AS dr2_source_id,",
            "    d.angular_distance AS angular_distance_mas,",
            "    d.magnitude_difference AS magnitude_difference_mag,",
            "    d.proper_motion_propagation AS proper_motion_propagation",
            "FROM gaiadr3.dr2_neighbourhood AS d",
            f"WHERE d.dr3_source_id IN ({values})",
            "ORDER BY d.dr3_source_id, d.angular_distance, d.dr2_source_id",
        ]
    )


def _client_order(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply deterministic distance then absolute-magnitude tie-breaking."""
    if frame.empty:
        return frame.reset_index(drop=True)
    ordered = frame.copy()
    ordered["_abs_magnitude_difference"] = ordered[
        "magnitude_difference_mag"
    ].abs()
    ordered = (
        ordered.sort_values(
            [
                "dr3_source_id",
                "angular_distance_mas",
                "_abs_magnitude_difference",
                "dr2_source_id",
            ],
            kind="stable",
            na_position="last",
        )
        .drop(columns=["_abs_magnitude_difference"])
        .drop_duplicates(["dr3_source_id", "dr2_source_id"], keep="first")
        .reset_index(drop=True)
    )
    return ordered


def query_gaia_dr2_neighbourhood_v2(
    source_ids: Iterable[int],
    *,
    config: GaiaDr2BridgeConfig = GaiaDr2BridgeConfig(),
    query_executor: Callable[[str, str, int], pd.DataFrame] = (
        _default_query_executor
    ),
) -> tuple[pd.DataFrame, list[GaiaDr2BridgeBatchReceipt]]:
    """Retrieve and client-order all DR2 neighbours for DR3 source batches."""
    identifiers = _source_ids(source_ids)
    if not identifiers:
        return pd.DataFrame(columns=_EXPECTED_COLUMNS), []

    frames: list[pd.DataFrame] = []
    receipts: list[GaiaDr2BridgeBatchReceipt] = []
    for batch_index, start in enumerate(
        range(0, len(identifiers), config.batch_size)
    ):
        batch = identifiers[start : start + config.batch_size]
        adql = build_gaia_dr2_bridge_adql_v2(batch)
        try:
            raw = query_executor(config.tap_url, adql, config.maxrec_per_batch)
            frame = _validate_batch(raw, set(batch))
        except Exception as error:
            if isinstance(error, GaiaDr2BridgeError):
                raise
            raise GaiaDr2BridgeError(
                f"Gaia DR2 bridge batch {batch_index} failed: "
                f"{type(error).__name__}: {error}"
            ) from error
        if len(frame) >= config.maxrec_per_batch:
            raise GaiaDr2BridgeError(
                f"Gaia bridge batch {batch_index} reached maxrec; "
                "result may be truncated"
            )
        receipts.append(
            GaiaDr2BridgeBatchReceipt(
                batch_index=batch_index,
                requested_source_count=len(batch),
                returned_row_count=len(frame),
                returned_source_count=int(frame["dr3_source_id"].nunique()),
                query_sha256=hashlib.sha256(adql.encode("utf-8")).hexdigest(),
            )
        )
        frames.append(frame)

    output = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=_EXPECTED_COLUMNS)
    )
    return _client_order(output), receipts
