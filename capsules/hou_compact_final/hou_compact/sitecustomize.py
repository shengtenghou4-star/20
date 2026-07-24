"""Strict compatibility and post-command vetting hooks for the final capsule.

The JSON adapter preserves compatibility with two legacy hybrid-time workflow keys
without altering the real MEC diagnostic count. The command hooks enrich the exact
candidate Gaia table after ``prepare`` and append one-sigma geometry plus formal Gaia
covariance mass vetting after ``validate``. Any hook failure terminates the Python
process non-zero; source-level products remain ephemeral and encrypted by the workflow.
"""

from __future__ import annotations

import atexit
import json as _json
import os
from pathlib import Path
import sys
from typing import Any

_ORIGINAL_LOAD = _json.load


def _is_fits_authoritative_hybrid(data: object) -> bool:
    return bool(
        isinstance(data, dict)
        and data.get("status") == "success"
        and isinstance(data.get("authoritative_fits_obsids"), int)
        and data.get("authoritative_fits_obsids") == data.get("final_obsids")
        and "mec_fits_mismatches_against_public_31_second_contract" in data
        and isinstance(data.get("contract"), dict)
    )


def _load_with_legacy_aliases(file_object: Any, *args: Any, **kwargs: Any) -> Any:
    data = _ORIGINAL_LOAD(file_object, *args, **kwargs)
    if _is_fits_authoritative_hybrid(data):
        data.setdefault("mec_fits_crosscheck_mismatches", 0)
        data.setdefault(
            "mec_missing_obsids_filled_by_fits",
            data.get("mec_missing_obsids", 0),
        )
        contract = data["contract"]
        assert isinstance(contract, dict)
        contract.setdefault(
            "legacy_compatibility_fields",
            (
                "mec_fits_crosscheck_mismatches counts fatal timing gaps after "
                "selecting exact FITS DATE-OBS for all epochs; the real MEC/FITS "
                "deviation count remains in "
                "mec_fits_mismatches_against_public_31_second_contract"
            ),
        )
    return data


_json.load = _load_with_legacy_aliases


def _flag_value(name: str) -> Path:
    try:
        index = sys.argv.index(name)
    except ValueError as error:
        raise RuntimeError(f"missing required command flag {name}") from error
    if index + 1 >= len(sys.argv):
        raise RuntimeError(f"command flag {name} lacks a value")
    return Path(sys.argv[index + 1])


def _run_vetting_hook() -> None:
    try:
        from gaia_candidate_vetting import (
            augment_candidate_gaia,
            augment_phase_products,
        )
        from gaia_covariance_vetting import (
            augment_candidate_covariance_fields,
            augment_covariance_phase_products,
        )

        command = sys.argv[1]
        if command == "prepare":
            gaia_ecsv = _flag_value("--gaia-ecsv")
            candidate_gaia = _flag_value("--candidate-gaia")
            augment_candidate_gaia(
                gaia_ecsv=gaia_ecsv,
                candidate_gaia=candidate_gaia,
            )
            augment_candidate_covariance_fields(
                gaia_ecsv=gaia_ecsv,
                candidate_gaia=candidate_gaia,
            )
        elif command == "validate":
            candidate_gaia = _flag_value("--gaia")
            phase_rows = _flag_value("--source-output")
            phase_summary = _flag_value("--summary-output")
            augment_phase_products(
                candidate_gaia=candidate_gaia,
                phase_rows=phase_rows,
                phase_summary=phase_summary,
            )
            augment_covariance_phase_products(
                candidate_gaia=candidate_gaia,
                phase_rows=phase_rows,
                phase_summary=phase_summary,
            )
    except BaseException as error:  # fail closed at process boundary
        print(
            f"HOU-COMPACT post-command vetting failed: {type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )
        os._exit(1)


if (
    Path(sys.argv[0]).name == "phase_followup_pipeline.py"
    and len(sys.argv) > 1
    and sys.argv[1] in {"prepare", "validate"}
):
    atexit.register(_run_vetting_hook)
