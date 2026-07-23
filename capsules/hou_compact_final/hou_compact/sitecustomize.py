"""Candidate-safe failure diagnostics for the final hybrid timing capsule.

Python imports this module automatically from the capsule PYTHONPATH.  It is inert
unless the explicit ``lamost_hybrid_time.py`` command exits through an uncaught
exception.  In that one case it writes only aggregate residual diagnostics to the
already-declared safe-summary path, then preserves the original exception and
non-zero exit.  No source identifier, obsid, path, timestamp or RV is emitted.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

_ORIGINAL_EXCEPTHOOK = sys.excepthook


def _flag_value(name: str) -> str | None:
    try:
        index = sys.argv.index(name)
    except ValueError:
        return None
    return sys.argv[index + 1] if index + 1 < len(sys.argv) else None


def _finite(value: object) -> float:
    result = float(str(value).strip())
    if not math.isfinite(result):
        raise ValueError("non-finite diagnostic value")
    return result


def _rounded_hist(values: list[float]) -> dict[str, int]:
    counts = Counter(f"{value:.1f}" for value in values)
    return {key: counts[key] for key in sorted(counts, key=float)}


def _write_hybrid_diagnostic(exc_type: type[BaseException]) -> None:
    if Path(sys.argv[0]).name != "lamost_hybrid_time.py":
        return
    safe_name = _flag_value("--safe-summary")
    if safe_name is None or len(sys.argv) < 4:
        return
    safe_path = Path(safe_name)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema_version": "1.1-diagnostic",
        "candidate_safe": True,
        "status": "failure_diagnostic",
        "error_type": exc_type.__name__,
        "claim_boundary": (
            "Aggregate hybrid-time failure diagnostics only. No source identity, "
            "obsid, coordinate, RV, timestamp, path, orbit row or classification is disclosed."
        ),
    }
    try:
        from astropy.io import fits
        from astropy.time import Time

        expected_path = Path(sys.argv[1])
        mec_path = Path(sys.argv[2])
        manifest_path = Path(sys.argv[3])

        with expected_path.open("r", encoding="utf-8-sig", newline="") as handle:
            expected_count = sum(1 for _ in csv.DictReader(handle, strict=True))

        mec: dict[str, tuple[float, float]] = {}
        with mec_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            for row in reader:
                token = str(row["obsid"])
                mec[token] = (
                    _finite(row["mid_mjd"]),
                    _finite(row["time_quantisation_half_width_days"]),
                )

        manifest: dict[str, Path] = {}
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            for row in reader:
                manifest[str(row["obsid"])] = Path(str(row["fits_path"]))

        residuals: list[float] = []
        allowed_values: list[float] = []
        excesses: list[float] = []
        mismatch_count = 0
        fractional_digits = Counter()
        for obsid, (mec_mjd, mec_error) in mec.items():
            path = manifest[obsid]
            with fits.open(
                path,
                mode="readonly",
                memmap=False,
                do_not_scale_image_data=True,
                ignore_missing_end=False,
            ) as hdul:
                date_obs = str(hdul[0].header["DATE-OBS"]).strip()
            fraction = date_obs.partition(".")[2]
            digits = len(fraction)
            fractional_digits[str(digits)] += 1
            fits_mjd = float(Time(date_obs, format="isot", scale="utc").mjd)
            fits_error = 0.5 * 10.0 ** (-digits) / 86400.0
            residual_seconds = abs(mec_mjd - fits_mjd) * 86400.0
            allowed_seconds = (mec_error + fits_error + 1e-12) * 86400.0
            excess_seconds = max(0.0, residual_seconds - allowed_seconds)
            residuals.append(residual_seconds)
            allowed_values.append(allowed_seconds)
            excesses.append(excess_seconds)
            mismatch_count += int(excess_seconds > 0.0)

        payload.update(
            {
                "expected_obsids": expected_count,
                "mec_crosschecks": len(residuals),
                "fits_manifest_obsids": len(manifest),
                "mismatch_count": mismatch_count,
                "maximum_residual_seconds": max(residuals, default=0.0),
                "maximum_allowed_seconds": max(allowed_values, default=0.0),
                "maximum_excess_seconds": max(excesses, default=0.0),
                "residual_seconds_rounded_0p1_histogram": _rounded_hist(residuals),
                "allowed_seconds_rounded_0p1_histogram": _rounded_hist(allowed_values),
                "excess_seconds_rounded_0p1_histogram": _rounded_hist(excesses),
                "fits_date_obs_fractional_second_digits": dict(
                    sorted(fractional_digits.items(), key=lambda item: int(item[0]))
                ),
                "diagnostic_contract": (
                    "absolute MEC/FITS residual compared with explicit MEC half-ULP "
                    "plus FITS half-ULP; failure remains fail-closed"
                ),
            }
        )
    except Exception as diagnostic_error:  # pragma: no cover - live fail-safe
        payload["diagnostic_error_type"] = type(diagnostic_error).__name__
    safe_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _candidate_safe_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback: object,
) -> None:
    try:
        _write_hybrid_diagnostic(exc_type)
    finally:
        _ORIGINAL_EXCEPTHOOK(exc_type, exc_value, traceback)


sys.excepthook = _candidate_safe_excepthook
