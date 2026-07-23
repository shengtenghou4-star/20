"""Exact-identity LAMOST RV acquisition through the anonymous browser form.

Candidate coordinates are used only to discover nearby public rows. A returned row
is accepted only when its Gaia DR3 character identifier exactly equals one of the
requested candidate IDs. The resulting per-spectrum RV/error rows use the common
HOU-COMPACT epoch schema and remain source-level encrypted research products.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import hashlib
import math
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from hou_compact.lamost import parse_exact_int_text
from hou_compact.lamost_search_form import SearchFormReceipt

_FORM_OUTPUT_COLUMNS = (
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
_REQUIRED_CANDIDATE_COLUMNS = {"source_id", "ra", "dec"}


class LamostFormRVError(RuntimeError):
    """Raised when anonymous form rows violate the exact-identity contract."""


@dataclass(frozen=True)
class FormRVConfig:
    batch_size: int = 20
    separation_arcsec: float = 2.0

    def __post_init__(self) -> None:
        if self.batch_size < 1 or self.batch_size > 100:
            raise ValueError("batch_size must lie in [1, 100]")
        if (
            not math.isfinite(self.separation_arcsec)
            or not 0 < self.separation_arcsec <= 10
        ):
            raise ValueError("separation_arcsec must lie in (0, 10]")

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FormRVBatchReceipt:
    batch_index: int
    input_target_count: int
    returned_row_count: int
    exact_identity_row_count: int
    csv_sha256: str
    form_receipt: dict[str, object]

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing columns: {missing}")


def normalize_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    """Validate exact source IDs and finite coordinates without changing row order."""

    _require_columns(candidates, _REQUIRED_CANDIDATE_COLUMNS, "candidates")
    output = candidates.copy()
    output["source_id"] = [
        parse_exact_int_text(value, name="candidate.source_id")
        for value in output["source_id"]
    ]
    if output["source_id"].duplicated().any():
        raise ValueError("candidates contain duplicate source_id rows")
    output["ra"] = pd.to_numeric(output["ra"], errors="coerce")
    output["dec"] = pd.to_numeric(output["dec"], errors="coerce")
    if not np.isfinite(output["ra"]).all() or not np.isfinite(output["dec"]).all():
        raise ValueError("candidate coordinates must be finite")
    if not output["ra"].between(0.0, 360.0, inclusive="left").all():
        raise ValueError("candidate RA must lie in [0, 360)")
    if not output["dec"].between(-90.0, 90.0, inclusive="both").all():
        raise ValueError("candidate Dec must lie in [-90, 90]")
    return output


def _chunks(frame: pd.DataFrame, size: int) -> Iterable[pd.DataFrame]:
    for start in range(0, len(frame), size):
        yield frame.iloc[start : start + size]


def build_browser_form_fields(
    candidates: pd.DataFrame,
    *,
    separation_arcsec: float,
) -> list[tuple[str, object]]:
    """Build the exact live form defaults for one coordinate-discovery batch."""

    if candidates.empty:
        raise ValueError("candidate batch must not be empty")
    lines = ["#ra,dec,sep"]
    for row in candidates.itertuples(index=False):
        lines.append(
            f"{float(row.ra):.12f},{float(row.dec):.12f},{separation_arcsec:.6g}"
        )
    fields: list[tuple[str, object]] = [
        ("sForm", "0"),
        ("pos.type", "proximity"),
        ("pos.radecTextarea", "\n".join(lines)),
        ("output.collection", "typical"),
        ("output.fmt", "csv"),
    ]
    fields.extend(
        (f"output.combined.{column}", "on") for column in _FORM_OUTPUT_COLUMNS
    )
    fields.append(("sBtn", "Search"))
    return fields


def _resolve_column(frame: pd.DataFrame, wanted: str) -> str | None:
    normalized = {
        str(column).strip().lower().replace(" ", "_"): str(column)
        for column in frame.columns
    }
    candidates = (
        wanted,
        f"combined.{wanted}",
        f"combined_{wanted}",
        f"catalogue_{wanted}",
    )
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    suffix = [
        original
        for name, original in normalized.items()
        if name.endswith(f".{wanted}") or name.endswith(f"_{wanted}")
    ]
    return suffix[0] if len(suffix) == 1 else None


def parse_browser_csv(body: bytes) -> pd.DataFrame:
    """Parse a bounded CSV response and normalize documented output columns."""

    try:
        raw = pd.read_csv(BytesIO(body), dtype="string")
    except (pd.errors.EmptyDataError, UnicodeDecodeError) as error:
        raise LamostFormRVError("anonymous form response was not readable CSV") from error
    resolved = {name: _resolve_column(raw, name) for name in _FORM_OUTPUT_COLUMNS}
    required = {"gaia_source_id", "obsid", "mjd", "rv", "rv_err"}
    missing = sorted(name for name in required if resolved[name] is None)
    if missing:
        raise LamostFormRVError(
            f"anonymous form CSV is missing required columns: {missing}"
        )
    output = pd.DataFrame(index=raw.index)
    for name in _FORM_OUTPUT_COLUMNS:
        source = resolved[name]
        output[name] = raw[source] if source is not None else pd.NA
    return output


def standardize_exact_rows(
    raw: pd.DataFrame,
    target_ids: set[int],
) -> pd.DataFrame:
    """Retain exact target identities and emit the common epoch schema."""

    output_columns = [
        "source_id",
        "obsid",
        "expid",
        "mjd",
        "vrad",
        "vrad_err",
        "success",
        "rvs_warn",
        "fiberstatus",
        "sn_b",
        "sn_r",
        "sn_z",
        "survey",
        "program",
        "source_match_mode",
        "class",
        "subclass",
    ]
    if raw.empty:
        return pd.DataFrame(columns=output_columns)

    parsed_ids: list[int | None] = []
    for value in raw["gaia_source_id"]:
        try:
            parsed_ids.append(
                parse_exact_int_text(value, name="form.gaia_source_id")
            )
        except (TypeError, ValueError):
            parsed_ids.append(None)

    # Never allow an invalid neighbour ID to force valid 19-digit identifiers
    # through float64.  Nullable Int64 preserves exact values and missingness.
    parsed_series = pd.Series(parsed_ids, index=raw.index, dtype="Int64")
    selected = raw.assign(_source_id=parsed_series)
    selected = selected.loc[selected["_source_id"].isin(target_ids)].copy()
    if selected.empty:
        return pd.DataFrame(columns=output_columns)

    selected["source_id"] = selected["_source_id"].astype("int64")
    selected["obsid"] = pd.to_numeric(
        selected["obsid"], errors="raise"
    ).astype("int64")
    if selected["obsid"].duplicated().any():
        raise LamostFormRVError(
            "anonymous form returned "
            f"{int(selected['obsid'].duplicated().sum())} duplicate obsids"
        )

    mjd = pd.to_numeric(selected["mjd"], errors="coerce")
    rv = pd.to_numeric(selected["rv"], errors="coerce")
    rv_error = pd.to_numeric(selected["rv_err"], errors="coerce")
    fiber = pd.to_numeric(selected["fibermask"], errors="coerce")
    fiberstatus = fiber.fillna(1).astype("int64")
    finite = np.isfinite(mjd) & np.isfinite(rv) & np.isfinite(rv_error)
    success = finite & rv_error.gt(0) & fiberstatus.eq(0)

    standardized = pd.DataFrame(
        {
            "source_id": selected["source_id"],
            "obsid": selected["obsid"],
            "expid": selected["obsid"],
            "mjd": mjd,
            "vrad": rv,
            "vrad_err": rv_error,
            "success": success.astype(bool),
            "rvs_warn": np.where(success, 0, 1).astype("int64"),
            "fiberstatus": fiberstatus,
            "sn_b": pd.to_numeric(selected["snrg"], errors="coerce"),
            "sn_r": pd.to_numeric(selected["snri"], errors="coerce"),
            "sn_z": pd.to_numeric(selected["snrz"], errors="coerce"),
            "survey": "lamost_dr8_v2_public_form",
            "program": "combined",
            "source_match_mode": (
                "exact_gaia_dr3_character_id_after_positional_discovery"
            ),
            "class": selected["class"].astype("string"),
            "subclass": selected["subclass"].astype("string"),
        }
    )
    return standardized.loc[:, output_columns].sort_values(
        ["source_id", "mjd", "obsid"], kind="stable"
    ).reset_index(drop=True)


def query_candidate_batches(
    candidates: pd.DataFrame,
    submitter: Callable[
        [list[tuple[str, object]]],
        tuple[bytes, SearchFormReceipt],
    ],
    *,
    config: FormRVConfig = FormRVConfig(),
) -> tuple[pd.DataFrame, list[FormRVBatchReceipt]]:
    """Run exact-identity browser-form queries over deterministic batches."""

    prepared = normalize_candidates(candidates)
    target_ids = set(prepared["source_id"].astype(int))
    frames: list[pd.DataFrame] = []
    receipts: list[FormRVBatchReceipt] = []
    seen_obsids: set[int] = set()
    for batch_index, batch in enumerate(_chunks(prepared, config.batch_size)):
        fields = build_browser_form_fields(
            batch,
            separation_arcsec=config.separation_arcsec,
        )
        body, form_receipt = submitter(fields)
        raw = parse_browser_csv(body)
        standardized = standardize_exact_rows(raw, target_ids)
        obsids = set(
            pd.to_numeric(
                standardized.get("obsid", pd.Series(dtype=int))
            ).astype(int)
        )
        duplicate_across_batches = seen_obsids.intersection(obsids)
        if duplicate_across_batches:
            raise LamostFormRVError(
                "one LAMOST obsid was returned in multiple positional batches"
            )
        seen_obsids.update(obsids)
        frames.append(standardized)
        receipts.append(
            FormRVBatchReceipt(
                batch_index=batch_index,
                input_target_count=len(batch),
                returned_row_count=len(raw),
                exact_identity_row_count=len(standardized),
                csv_sha256=hashlib.sha256(body).hexdigest(),
                form_receipt=form_receipt.to_record(),
            )
        )
    combined = (
        pd.concat(frames, ignore_index=True, sort=False)
        if frames
        else standardize_exact_rows(pd.DataFrame(), set())
    )
    return combined.sort_values(
        ["source_id", "mjd", "obsid"], kind="stable"
    ).reset_index(drop=True), receipts


def candidate_safe_form_rv_summary(
    target_count: int,
    rows: pd.DataFrame,
    receipts: Iterable[FormRVBatchReceipt],
    config: FormRVConfig,
) -> dict[str, Any]:
    """Aggregate anonymous form coverage without identifiers, positions or RV values."""

    source_counts = (
        rows.groupby("source_id", sort=False).size()
        if not rows.empty
        else pd.Series(dtype=int)
    )
    success = rows.get(
        "success", pd.Series(False, index=rows.index)
    ).astype(bool)
    clean_counts = (
        rows.loc[success].groupby("source_id", sort=False).size()
        if success.any()
        else pd.Series(dtype=int)
    )
    receipt_list = list(receipts)
    return {
        "target_count": int(target_count),
        "matched_source_count": int(len(source_counts)),
        "unmatched_source_count": int(target_count - len(source_counts)),
        "exact_identity_epoch_rows": int(len(rows)),
        "quality_pass_epoch_rows": int(success.sum()),
        "raw_epoch_threshold_counts": {
            "ge_2": int(source_counts.ge(2).sum()),
            "ge_3": int(source_counts.ge(3).sum()),
            "ge_5": int(source_counts.ge(5).sum()),
            "ge_7": int(source_counts.ge(7).sum()),
            "ge_10": int(source_counts.ge(10).sum()),
        },
        "quality_pass_threshold_counts": {
            "ge_2": int(clean_counts.ge(2).sum()),
            "ge_3": int(clean_counts.ge(3).sum()),
            "ge_5": int(clean_counts.ge(5).sum()),
            "ge_7": int(clean_counts.ge(7).sum()),
            "ge_10": int(clean_counts.ge(10).sum()),
        },
        "request_count": len(receipt_list),
        "configuration": config.to_record(),
        "claim_boundary": (
            "Coordinates only discover nearby public rows. Every retained row passed exact "
            "Gaia DR3 character identity and carries a quoted RV uncertainty; this remains "
            "coverage data, not evidence of variability, binarity or a compact companion."
        ),
    }
