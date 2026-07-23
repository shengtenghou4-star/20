#!/usr/bin/env python3
"""Strict delimiter detection for LAMOST catalogue streams.

LAMOST DR8 labels its download as CSV while the official v1.0 LRS catalogue is
pipe-delimited.  This module keeps delimiter handling explicit, bounded and
fail-closed instead of silently accepting a one-column parse.
"""

from __future__ import annotations

import csv
import itertools
from collections.abc import Iterable, Iterator
from types import ModuleType
from typing import Any

_ALLOWED_DELIMITERS = (",", "|", "\t")
_ORIGINAL_DICT_READER = csv.DictReader
_ORIGINAL_DICT_WRITER = csv.DictWriter
_CSV_ERROR = csv.Error


class DelimiterContractError(RuntimeError):
    """Raised when a delimited header cannot be resolved unambiguously."""


def _normalized(fields: list[str]) -> list[str]:
    return [field.strip().lower().lstrip("\ufeff") for field in fields]


def detect_delimiter(header_line: str) -> tuple[str, list[str]]:
    """Return the unique supported delimiter yielding the richest valid header."""

    if not header_line:
        raise DelimiterContractError("delimited stream has no header line")
    candidates: list[tuple[int, str, list[str]]] = []
    for delimiter in _ALLOWED_DELIMITERS:
        try:
            fields = next(csv.reader([header_line], delimiter=delimiter, strict=True))
        except csv.Error:
            continue
        normalized = _normalized(fields)
        if len(fields) < 2 or any(not field for field in normalized):
            continue
        if len(set(normalized)) != len(normalized):
            continue
        candidates.append((len(fields), delimiter, fields))
    if not candidates:
        raise DelimiterContractError(
            "header does not match any supported delimiter contract"
        )
    maximum = max(count for count, _, _ in candidates)
    winners = [(delimiter, fields) for count, delimiter, fields in candidates if count == maximum]
    if len(winners) != 1:
        delimiters = [delimiter for delimiter, _ in winners]
        raise DelimiterContractError(
            f"header delimiter is ambiguous among {delimiters!r}"
        )
    return winners[0]


def delimiter_aware_dict_reader(
    source: Iterable[str],
    *args: Any,
    **kwargs: Any,
) -> csv.DictReader:
    """Create a strict DictReader after one-line bounded delimiter detection."""

    if "delimiter" in kwargs or "dialect" in kwargs:
        return _ORIGINAL_DICT_READER(source, *args, **kwargs)
    iterator: Iterator[str] = iter(source)
    try:
        header_line = next(iterator)
    except StopIteration as error:
        raise DelimiterContractError("delimited stream is empty") from error
    delimiter, _ = detect_delimiter(header_line)
    replay = itertools.chain((header_line,), iterator)
    return _ORIGINAL_DICT_READER(replay, *args, delimiter=delimiter, **kwargs)


class _CsvProxy:
    """Minimal csv-module proxy used only inside the private stream module."""

    Error = _CSV_ERROR
    DictWriter = _ORIGINAL_DICT_WRITER

    @staticmethod
    def DictReader(source: Iterable[str], *args: Any, **kwargs: Any) -> csv.DictReader:
        return delimiter_aware_dict_reader(source, *args, **kwargs)


def install_csv_proxy(module: ModuleType) -> None:
    """Install delimiter-aware parsing without mutating Python's global csv module."""

    module.csv = _CsvProxy()
