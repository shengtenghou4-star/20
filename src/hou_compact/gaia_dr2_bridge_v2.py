"""TAP-compatible Gaia DR3-to-DR2 bridge retrieval and audit.

Gaia's TAP parser rejects scalar expressions such as ``ABS(...)`` in this
``ORDER BY`` context. The server query therefore orders only by plain columns;
HOU-COMPACT applies the absolute-magnitude tie-break deterministically after the
complete bounded response has been validated and preserves that rule during the
one-row-per-source ambiguity audit.
"""

from __future__ import annotations

import hashlib
import math
import time
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
_AUDITED_COLUMNS = (
    "source_id",
    "dr2_source_id",
    "dr2_bridge_status",
    "dr2_neighbour_count",
    "dr2_angular_distance_mas",
    "dr2_second_distance_mas",
    "dr2_distance_margin_mas",
    "dr2_magnitude_difference_mag",
    "dr2_proper_motion_propagation",
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
    query_retries: int = 0,
    retry_backoff_seconds: float = 0.0,
) -> tuple[pd.DataFrame, list[GaiaDr2BridgeBatchReceipt]]:
    """Retrieve and client-order all DR2 neighbours for DR3 source batches.

    Each TAP batch is retried independently after transport/service exceptions. A
    scientific response-contract failure is never retried: once a response exists,
    missing columns, unexpected source identifiers, truncation, or invalid values fail
    closed immediately. This prevents one transient failure near the end of a 5,000-source
    bridge from discarding all previously successful remote work within the attempt.
    """
    identifiers = _source_ids(source_ids)
    if not identifiers:
        return pd.DataFrame(columns=_EXPECTED_COLUMNS), []
    if isinstance(query_retries, bool) or not isinstance(query_retries, int):
        raise TypeError("query_retries must be an integer")
    if query_retries < 0:
        raise ValueError("query_retries must be non-negative")
    if not math.isfinite(retry_backoff_seconds) or retry_backoff_seconds < 0:
        raise ValueError("retry_backoff_seconds must be finite and non-negative")

    frames: list[pd.DataFrame] = []
    receipts: list[GaiaDr2BridgeBatchReceipt] = []
    for batch_index, start in enumerate(
        range(0, len(identifiers), config.batch_size)
    ):
        batch = identifiers[start : start + config.batch_size]
        adql = build_gaia_dr2_bridge_adql_v2(batch)
        raw: pd.DataFrame | None = None
        last_error: BaseException | None = None
        for attempt_index in range(query_retries + 1):
            try:
                raw = query_executor(config.tap_url, adql, config.maxrec_per_batch)
                break
            except Exception as error:  # remote transport/service boundary
                last_error = error
                if attempt_index >= query_retries:
                    break
                delay = min(retry_backoff_seconds * (2**attempt_index), 60.0)
                if delay > 0:
                    time.sleep(delay)
        if raw is None:
            assert last_error is not None
            raise GaiaDr2BridgeError(
                f"Gaia DR2 bridge batch {batch_index} failed after "
                f"{query_retries + 1} attempts: {type(last_error).__name__}: "
                f"{last_error}"
            ) from last_error

        # Response validation is a scientific contract. Never hide or retry it.
        frame = _validate_batch(raw, set(batch))
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


def audit_gaia_dr2_bridge_v2(
    neighbours: pd.DataFrame,
    *,
    maximum_nearest_distance_mas: float = 1000.0,
    minimum_distance_margin_mas: float = 5.0,
) -> pd.DataFrame:
    """Select a release bridge while preserving absolute-magnitude tie-breaking."""
    if (
        not math.isfinite(maximum_nearest_distance_mas)
        or maximum_nearest_distance_mas <= 0
    ):
        raise ValueError(
            "maximum_nearest_distance_mas must be finite and positive"
        )
    if (
        not math.isfinite(minimum_distance_margin_mas)
        or minimum_distance_margin_mas < 0
    ):
        raise ValueError(
            "minimum_distance_margin_mas must be finite and non-negative"
        )
    requested = set(
        pd.to_numeric(neighbours["dr3_source_id"], errors="raise").astype(
            "int64"
        )
    )
    frame = _validate_batch(neighbours, requested)
    if frame.empty:
        return pd.DataFrame(columns=_AUDITED_COLUMNS)

    records: list[dict[str, object]] = []
    for dr3_source_id, group in frame.groupby("dr3_source_id", sort=True):
        ordered = _client_order(group).reset_index(drop=True)
        nearest = ordered.iloc[0]
        neighbour_count = len(ordered)
        second_distance = (
            float(ordered.iloc[1]["angular_distance_mas"])
            if neighbour_count > 1
            else float("nan")
        )
        margin = (
            second_distance - float(nearest["angular_distance_mas"])
            if neighbour_count > 1
            else float("inf")
        )
        status = "accepted_unique_or_separated_nearest"
        if float(nearest["angular_distance_mas"]) > maximum_nearest_distance_mas:
            status = "rejected_nearest_too_distant"
        elif neighbour_count > 1 and margin < minimum_distance_margin_mas:
            status = "rejected_ambiguous_nearest"
        records.append(
            {
                "source_id": int(dr3_source_id),
                "dr2_source_id": int(nearest["dr2_source_id"]),
                "dr2_bridge_status": status,
                "dr2_neighbour_count": neighbour_count,
                "dr2_angular_distance_mas": float(
                    nearest["angular_distance_mas"]
                ),
                "dr2_second_distance_mas": second_distance,
                "dr2_distance_margin_mas": margin,
                "dr2_magnitude_difference_mag": float(
                    nearest["magnitude_difference_mag"]
                ),
                "dr2_proper_motion_propagation": bool(
                    nearest["proper_motion_propagation"]
                ),
            }
        )
    return (
        pd.DataFrame.from_records(records, columns=_AUDITED_COLUMNS)
        .sort_values("source_id", kind="stable")
        .reset_index(drop=True)
    )
