"""Gaia DR3-to-DR2 identifier bridge for DESI FIBERMAP ``REF_ID`` recovery.

DESI DR1 targeting metadata records Gaia DR2 source identifiers when ``REF_CAT='G2'``.
Gaia explicitly warns that source identifiers are not stable across releases, so DR3 IDs
must be connected to DR2 through ``gaiadr3.dr2_neighbourhood`` rather than compared
numerically. This module retrieves and audits that bridge without guessing ambiguous
release-to-release associations.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass

import pandas as pd
import pyvo

from hou_compact.gaia import DEFAULT_GAIA_TAP_URL

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


class GaiaDr2BridgeError(RuntimeError):
    """Raised when Gaia DR2-neighbourhood retrieval or validation fails."""


@dataclass(frozen=True)
class GaiaDr2BridgeConfig:
    """Bounded Gaia TAP settings for release-identifier bridge queries."""

    tap_url: str = DEFAULT_GAIA_TAP_URL
    batch_size: int = 250
    maxrec_per_batch: int = 5000

    def __post_init__(self) -> None:
        if not self.tap_url.startswith("https://"):
            raise ValueError("tap_url must use HTTPS")
        if not 1 <= self.batch_size <= 1000:
            raise ValueError("batch_size must lie in [1, 1000]")
        if self.maxrec_per_batch < self.batch_size:
            raise ValueError("maxrec_per_batch must be at least batch_size")


@dataclass(frozen=True)
class GaiaDr2BridgeBatchReceipt:
    """Candidate-safe receipt for one Gaia neighbourhood batch."""

    batch_index: int
    requested_source_count: int
    returned_row_count: int
    returned_source_count: int
    query_sha256: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _source_ids(values: Iterable[int]) -> list[int]:
    result: set[int] = set()
    for raw in values:
        if isinstance(raw, bool):
            raise TypeError("source IDs must be integers, not booleans")
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise TypeError(f"invalid Gaia DR3 source ID: {raw!r}") from error
        if value < 0 or value > 2**63 - 1:
            raise ValueError(
                f"Gaia DR3 source ID outside signed 64-bit range: {value}"
            )
        result.add(value)
    return sorted(result)


def build_gaia_dr2_bridge_adql(source_ids: Iterable[int]) -> str:
    """Build a frozen DR2-neighbourhood query for one source-ID batch."""
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
            "ORDER BY d.dr3_source_id, d.angular_distance,",
            "         ABS(d.magnitude_difference), d.dr2_source_id",
        ]
    )


def _default_query_executor(
    tap_url: str,
    adql: str,
    maxrec: int,
) -> pd.DataFrame:
    service = pyvo.dal.TAPService(tap_url)
    return service.run_sync(adql, maxrec=maxrec).to_table().to_pandas()


def _validate_batch(frame: pd.DataFrame, requested: set[int]) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [str(column).strip().lower() for column in result.columns]
    missing = sorted(set(_EXPECTED_COLUMNS) - set(result.columns))
    if missing:
        raise GaiaDr2BridgeError(
            f"Gaia bridge response is missing columns: {missing}"
        )
    result = result.loc[:, list(_EXPECTED_COLUMNS)]
    if result.empty:
        return result.astype(
            {
                "dr3_source_id": "int64",
                "dr2_source_id": "int64",
                "angular_distance_mas": "float64",
                "magnitude_difference_mag": "float64",
                "proper_motion_propagation": "bool",
            }
        )
    for name in ("dr3_source_id", "dr2_source_id"):
        numeric = pd.to_numeric(result[name], errors="raise")
        if (numeric % 1 != 0).any():
            raise GaiaDr2BridgeError(f"non-integral identifier in {name}")
        result[name] = numeric.astype("int64")
    unexpected = sorted(set(result["dr3_source_id"].astype(int)) - requested)
    if unexpected:
        raise GaiaDr2BridgeError(
            "Gaia bridge returned source IDs outside the current batch: "
            f"{unexpected[:5]}"
        )
    result["angular_distance_mas"] = pd.to_numeric(
        result["angular_distance_mas"], errors="raise"
    ).astype(float)
    result["magnitude_difference_mag"] = pd.to_numeric(
        result["magnitude_difference_mag"], errors="coerce"
    ).astype(float)
    if not result["angular_distance_mas"].map(math.isfinite).all():
        raise GaiaDr2BridgeError("non-finite Gaia DR2/DR3 angular distance")
    if (result["angular_distance_mas"] < 0).any():
        raise GaiaDr2BridgeError("negative Gaia DR2/DR3 angular distance")
    result["proper_motion_propagation"] = (
        result["proper_motion_propagation"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "t", "yes"})
    )
    return result


def query_gaia_dr2_neighbourhood(
    source_ids: Iterable[int],
    *,
    config: GaiaDr2BridgeConfig = GaiaDr2BridgeConfig(),
    query_executor: Callable[[str, str, int], pd.DataFrame] = (
        _default_query_executor
    ),
) -> tuple[pd.DataFrame, list[GaiaDr2BridgeBatchReceipt]]:
    """Retrieve all DR2 neighbours for DR3 sources in deterministic batches."""
    identifiers = _source_ids(source_ids)
    if not identifiers:
        return pd.DataFrame(columns=_EXPECTED_COLUMNS), []
    frames: list[pd.DataFrame] = []
    receipts: list[GaiaDr2BridgeBatchReceipt] = []
    for batch_index, start in enumerate(
        range(0, len(identifiers), config.batch_size)
    ):
        batch = identifiers[start : start + config.batch_size]
        adql = build_gaia_dr2_bridge_adql(batch)
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
    if not output.empty:
        output = output.sort_values(
            [
                "dr3_source_id",
                "angular_distance_mas",
                "magnitude_difference_mag",
                "dr2_source_id",
            ],
            kind="stable",
            na_position="last",
        ).drop_duplicates(["dr3_source_id", "dr2_source_id"], keep="first")
        output = output.reset_index(drop=True)
    return output, receipts


def audit_gaia_dr2_bridge(
    neighbours: pd.DataFrame,
    *,
    maximum_nearest_distance_mas: float = 1000.0,
    minimum_distance_margin_mas: float = 5.0,
) -> pd.DataFrame:
    """Select only unambiguous DR2 counterparts while preserving rejected rows."""
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
        ordered = group.sort_values(
            ["angular_distance_mas", "magnitude_difference_mag", "dr2_source_id"],
            kind="stable",
            na_position="last",
        ).reset_index(drop=True)
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
