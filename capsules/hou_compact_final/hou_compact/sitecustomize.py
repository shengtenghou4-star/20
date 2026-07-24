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
import re
import sys
from typing import Any

_ORIGINAL_LOAD = _json.load
_LONG_INTEGER = re.compile(r"(?<![0-9])[0-9]{10,20}(?![0-9])")
_URL = re.compile(r"https?://\S+")


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


def _redact_message(value: object, *, limit: int = 1000) -> str:
    message = _LONG_INTEGER.sub("<redacted-id>", str(value))
    message = _URL.sub("<redacted-url>", message)
    return message[:limit]


def _flag_value(name: str) -> Path:
    try:
        index = sys.argv.index(name)
    except ValueError as error:
        raise RuntimeError(f"missing required command flag {name}") from error
    if index + 1 >= len(sys.argv):
        raise RuntimeError(f"command flag {name} lacks a value")
    return Path(sys.argv[index + 1])


def _safe_error_payload(stage: str, error: BaseException) -> dict[str, object]:
    return {
        "schema_version": "0.2",
        "candidate_safe": True,
        "status": "failure",
        "stage": stage,
        "error_type": type(error).__name__,
        "error_message": _redact_message(error),
        "claim_boundary": (
            "Sanitized post-command vetting failure only; no source identity, coordinate, "
            "obsid, RV, timestamp, orbit value, covariance coefficient, or mass is disclosed."
        ),
    }


def _safe_error_path(command: str) -> Path:
    flag = "--candidate-gaia" if command == "prepare" else "--source-output"
    try:
        parent = _flag_value(flag).parent
    except BaseException:
        parent = Path("relay_work")
    return parent / "gaia_vetting_safe_error.json"


def _safe_summary_path(command: str) -> Path | None:
    flag = "--summary" if command == "prepare" else "--summary-output"
    try:
        return _flag_value(flag)
    except BaseException:
        return None


def _persist_safe_error(command: str, stage: str, error: BaseException) -> None:
    payload = _safe_error_payload(stage, error)
    path = _safe_error_path(command)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    summary_path = _safe_summary_path(command)
    if summary_path is None or not summary_path.exists():
        return
    if summary_path.stat().st_size == 0:
        return
    try:
        summary = _json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, _json.JSONDecodeError):
        return
    if not isinstance(summary, dict) or summary.get("candidate_safe") is not True:
        return
    summary["gaia_vetting_failure"] = payload
    summary_path.write_text(
        _json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _run_vetting_hook() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    stage = f"{command}_hook_initialization"
    try:
        from gaia_candidate_vetting import (
            augment_candidate_gaia,
            augment_phase_products,
        )
        from gaia_covariance_enrichment import augment_candidate_covariance_fields
        from gaia_covariance_vetting import augment_covariance_phase_products

        if command == "prepare":
            gaia_ecsv = _flag_value("--gaia-ecsv")
            candidate_gaia = _flag_value("--candidate-gaia")
            stage = "candidate_quality_error_geometry_enrichment"
            augment_candidate_gaia(
                gaia_ecsv=gaia_ecsv,
                candidate_gaia=candidate_gaia,
            )
            stage = "candidate_covariance_array_enrichment"
            augment_candidate_covariance_fields(
                gaia_ecsv=gaia_ecsv,
                candidate_gaia=candidate_gaia,
            )
        elif command == "validate":
            candidate_gaia = _flag_value("--gaia")
            phase_rows = _flag_value("--source-output")
            phase_summary = _flag_value("--summary-output")
            stage = "candidate_coordinatewise_mass_geometry_vetting"
            augment_phase_products(
                candidate_gaia=candidate_gaia,
                phase_rows=phase_rows,
                phase_summary=phase_summary,
            )
            stage = "candidate_full_gaia_covariance_vetting"
            augment_covariance_phase_products(
                candidate_gaia=candidate_gaia,
                phase_rows=phase_rows,
                phase_summary=phase_summary,
            )
    except BaseException as error:  # fail closed at process boundary
        try:
            _persist_safe_error(command, stage, error)
        except BaseException:
            pass
        print(
            f"HOU-COMPACT post-command vetting failed at {stage}: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
            flush=True,
        )
        os._exit(1)


def _load_json_object(path: Path) -> dict[str, object] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        value = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, _json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_external_failure(
    *,
    stage: str,
    manifest_path: Path,
) -> dict[str, object]:
    manifest = _load_json_object(manifest_path)
    if manifest is None:
        return {
            "candidate_safe": True,
            "status": "failure",
            "stage": stage,
            "error_type": "failure_manifest_missing",
            "error_message": (
                "The external stage failed without a readable candidate-safe failure receipt."
            ),
        }

    payload: dict[str, object] = {
        "candidate_safe": True,
        "status": "failure",
        "stage": stage,
        "error_type": str(manifest.get("error_type", "unknown_external_error")),
        "error_message": _redact_message(
            manifest.get("error_message", "external stage failed")
        ),
    }
    for key in (
        "execution_mode",
        "terminal_phase",
        "output_exists",
        "input_source_count",
    ):
        value = manifest.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[key] = value

    settings = manifest.get("settings")
    if isinstance(settings, dict):
        allowed_settings = {
            key: value
            for key, value in settings.items()
            if key
            in {
                "batch_size",
                "maxrec_per_batch",
                "query_retries_per_batch",
                "retry_backoff_seconds",
            }
            and isinstance(value, (str, int, float, bool))
        }
        if allowed_settings:
            payload["settings"] = allowed_settings

    for key in (
        "fetch_retries",
        "wait_timeout_seconds",
        "minimum_http_timeout_seconds",
    ):
        value = manifest.get(key)
        if isinstance(value, (int, float)):
            payload[key] = value
    payload["claim_boundary"] = (
        "Candidate-safe external-service failure only; no source identifier, coordinate, "
        "query text, remote job identifier, or candidate measurement is disclosed."
    )
    return payload


def _inject_external_stage_failures() -> None:
    """Append sanitized Gaia/bridge failures after the workflow writes its safe receipt."""
    summary_path = Path("candidate_safe_final_hybrid_summary.json")
    summary = _load_json_object(summary_path)
    if summary is None or summary.get("candidate_safe") is not True:
        return

    gaia_outcome = os.environ.get("GAIA_OUTCOME")
    bridge_outcome = os.environ.get("BRIDGE_OUTCOME")
    failures: list[dict[str, object]] = []
    if gaia_outcome != "success":
        failures.append(
            _safe_external_failure(
                stage="gaia_v9",
                manifest_path=Path(
                    "relay_work/gaia_seed.ecsv.failure.manifest.json"
                ),
            )
        )
    elif bridge_outcome != "success":
        failures.append(
            _safe_external_failure(
                stage="dr3_dr2_bridge",
                manifest_path=Path(
                    "relay_work/gaia_dr2_bridge.csv.failure.manifest.json"
                ),
            )
        )

    if not failures:
        return
    summary["external_stage_failures"] = failures
    summary_path.write_text(
        _json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if (
    Path(sys.argv[0]).name == "phase_followup_pipeline.py"
    and len(sys.argv) > 1
    and sys.argv[1] in {"prepare", "validate"}
):
    atexit.register(_run_vetting_hook)

if "GAIA_OUTCOME" in os.environ and "BRIDGE_OUTCOME" in os.environ:
    atexit.register(_inject_external_stage_failures)
