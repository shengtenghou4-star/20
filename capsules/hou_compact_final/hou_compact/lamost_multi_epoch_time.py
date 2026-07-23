#!/usr/bin/env python3
"""Compatibility bridge for legacy phase-followup imports.

The final capsule's production workflow calls :mod:`lamost_mec_utc_time` directly.
This wrapper preserves the older ``extract_exact_times`` callable while routing it
through the same verified UTC+8-corrected parser.
"""

from __future__ import annotations

import gzip
import tempfile
from pathlib import Path
from typing import TextIO

from lamost_mec_utc_time import MecTimeError, extract


def extract_exact_times(
    *,
    expected_path: Path,
    multi_epoch_stream: TextIO,
    output_path: Path,
    receipt_path: Path,
    checkpoint_every_rows: int = 100_000,
) -> dict[str, object]:
    if checkpoint_every_rows < 1:
        raise ValueError("checkpoint_every_rows must be positive")
    with tempfile.TemporaryDirectory() as temporary:
        catalogue = Path(temporary) / "mec.csv.gz"
        try:
            with gzip.open(
                catalogue,
                mode="wt",
                encoding="utf-8",
                newline="",
            ) as target:
                for chunk in multi_epoch_stream:
                    target.write(chunk)
        except (OSError, TypeError) as error:
            raise MecTimeError(
                f"legacy MEC stream staging failed: {type(error).__name__}"
            ) from error
        return extract(
            expected_path=expected_path,
            catalogue_gz=catalogue,
            output_path=output_path,
            receipt_path=receipt_path,
        )
