"""Parse LAMOST browser-form tabular responses without assuming a delimiter.

The live DR8 v2.0 form labels its output as CSV but currently emits pipe-delimited
text with underscore-prefixed table names.  Parsing is therefore based on the
header line and supports pipe, comma, or tab delimiters.  This module contains no
network logic and never summarizes row values.
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd


class LamostFormResponseError(RuntimeError):
    """Raised when a public browser-form response is not a supported table."""


def detect_delimiter(body: bytes) -> str:
    """Choose the strongest supported delimiter from the first non-empty line."""

    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise LamostFormResponseError("form response is not UTF-8 text") from error
    header = next((line for line in text.splitlines() if line.strip()), "")
    if not header:
        raise LamostFormResponseError("form response contains no header line")
    candidates = {"|": header.count("|"), ",": header.count(","), "\t": header.count("\t")}
    delimiter, count = max(candidates.items(), key=lambda item: item[1])
    if count < 1:
        raise LamostFormResponseError("form response has no supported delimiter")
    return delimiter


def parse_delimited_response(body: bytes) -> pd.DataFrame:
    """Parse a pipe/comma/tab response and normalize column labels."""

    delimiter = detect_delimiter(body)
    try:
        frame = pd.read_csv(
            BytesIO(body),
            sep=delimiter,
            dtype="string",
            encoding="utf-8-sig",
            engine="python",
        )
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as error:
        raise LamostFormResponseError("form response was not a readable delimited table") from error
    frame.columns = [str(column).strip() for column in frame.columns]
    removable = [
        column
        for column in frame.columns
        if not str(column).strip()
        or str(column).lower().startswith("unnamed:")
    ]
    if removable:
        frame = frame.drop(columns=removable)
    if not len(frame.columns):
        raise LamostFormResponseError("form response table contains no named columns")
    return frame


def resolve_column(frame: pd.DataFrame, wanted: str) -> str | None:
    """Resolve documented plain/dotted/underscored LAMOST output labels."""

    normalized = {
        str(column).strip().lower().replace(" ", "_"): str(column)
        for column in frame.columns
    }
    for candidate in (
        wanted,
        f"combined.{wanted}",
        f"combined_{wanted}",
        f"catalogue_{wanted}",
    ):
        if candidate in normalized:
            return normalized[candidate]
    suffix_matches = [
        original
        for name, original in normalized.items()
        if name.endswith(f".{wanted}") or name.endswith(f"_{wanted}")
    ]
    return suffix_matches[0] if len(suffix_matches) == 1 else None
