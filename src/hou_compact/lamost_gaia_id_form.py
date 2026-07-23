"""Direct anonymous LAMOST search-form queries by exact Gaia DR3 source ID.

LAMOST DR8 v2.0 exposes a public ``gaiasourcearea`` list constraint. This
module builds that form payload without coordinates, so the database can use
its native Gaia-ID index rather than evaluating many positional cones. Source
IDs and returned rows remain source-level research data and must be encrypted
before persistence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Iterable

import numpy as np
import pandas as pd

from hou_compact.lamost import parse_exact_int_text
from hou_compact.lamost_form_response import parse_delimited_response, resolve_column
from hou_compact.lamost_form_rv import standardize_exact_rows
from hou_compact.lamost_search_form import SearchFormReceipt

_OUTPUT_COLUMNS = (
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
_NUMERIC_MEASUREMENT_COLUMNS = (
    "mjd",
    "rv",
    "rv_err",
    "snrg",
    "snri",
    "snrz",
    "fibermask",
)


@dataclass(frozen=True)
class GaiaIDFormReceipt:
    input_target_count: int
    returned_row_count: int
    exact_identity_row_count: int
    response_sha256: str
    form_receipt: dict[str, object]

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def normalize_source_ids(values: Iterable[object]) -> list[int]:
    """Return unique exact positive Gaia DR3 integer identifiers in input order."""

    source_ids = [
        parse_exact_int_text(value, name="candidate.source_id")
        for value in values
    ]
    if any(source_id <= 0 for source_id in source_ids):
        raise ValueError("Gaia DR3 source IDs must be positive")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("Gaia DR3 source IDs must be unique")
    return source_ids


def build_gaia_id_form_fields(source_ids: Iterable[object]) -> list[tuple[str, object]]:
    """Build the public browser-form payload for an exact Gaia DR3 ID list."""

    normalized = normalize_source_ids(source_ids)
    if not normalized:
        raise ValueError("at least one Gaia DR3 source ID is required")
    lines = ["#gaia_source_id", *(str(source_id) for source_id in normalized)]
    fields: list[tuple[str, object]] = [
        ("sForm", "0"),
        ("pos.type", "none"),
        ("gaiasourcearea", "\n".join(lines)),
        ("output.collection", "typical"),
        ("output.fmt", "csv"),
    ]
    fields.extend(
        (f"output.combined.{column}", "on") for column in _OUTPUT_COLUMNS
    )
    fields.append(("sBtn", "Search"))
    return fields


def _plain_float_series(series: pd.Series) -> pd.Series:
    """Convert nullable numeric values to float64 with ordinary NaN missingness."""

    numeric = pd.to_numeric(series, errors="coerce")
    values = numeric.to_numpy(dtype="float64", na_value=np.nan)
    return pd.Series(values, index=series.index, dtype="float64")


def normalize_form_table(body: bytes) -> pd.DataFrame:
    """Parse a LAMOST delimited response into the frozen output-column contract."""

    raw = parse_delimited_response(body)
    resolved = {column: resolve_column(raw, column) for column in _OUTPUT_COLUMNS}
    required = {"gaia_source_id", "obsid", "mjd", "rv", "rv_err"}
    missing = sorted(column for column in required if resolved[column] is None)
    if missing:
        raise RuntimeError(f"Gaia-ID form table is missing required columns: {missing}")
    output = pd.DataFrame(index=raw.index)
    for column in _OUTPUT_COLUMNS:
        source = resolved[column]
        output[column] = raw[source] if source is not None else pd.NA
    for column in _NUMERIC_MEASUREMENT_COLUMNS:
        output[column] = _plain_float_series(output[column])
    return output


def standardize_gaia_id_response(
    body: bytes,
    source_ids: Iterable[object],
    form_receipt: SearchFormReceipt,
) -> tuple[pd.DataFrame, GaiaIDFormReceipt]:
    """Retain exact requested identities and return common RV epoch rows."""

    normalized = normalize_source_ids(source_ids)
    raw = normalize_form_table(body)
    epochs = standardize_exact_rows(raw, set(normalized)).copy()
    if not epochs.empty:
        epochs["source_match_mode"] = (
            "exact_gaia_dr3_character_id_direct_form_constraint"
        )
    receipt = GaiaIDFormReceipt(
        input_target_count=len(normalized),
        returned_row_count=len(raw),
        exact_identity_row_count=len(epochs),
        response_sha256=hashlib.sha256(body).hexdigest(),
        form_receipt=form_receipt.to_record(),
    )
    return epochs, receipt
