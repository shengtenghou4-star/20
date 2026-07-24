#!/usr/bin/env python3
"""Run the covariance enrichment/parity contract on one de-identified live Gaia row."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np
from astropy.table import Table

CAPSULE = Path(__file__).resolve().parents[1] / "capsules" / "hou_compact_final" / "hou_compact"
sys.path.insert(0, str(CAPSULE))

from gaia_covariance_enrichment import augment_candidate_covariance_fields  # noqa: E402
from hou_compact.gaia_covariance import coerce_correlation_vector  # noqa: E402
from hou_compact.reference_covariance import compare_with_nsstools  # noqa: E402

_FAKE_SOURCE = "1234567890123456789"
_LONG_INTEGER = re.compile(r"(?<![0-9])[0-9]{10,20}(?![0-9])")
_CANDIDATE_FIELDS = (
    "source_id",
    "nss_solution_type",
    "period",
    "period_error",
    "t_periastron",
    "t_periastron_error",
    "eccentricity",
    "eccentricity_error",
    "arg_periastron",
    "arg_periastron_error",
    "center_of_mass_velocity",
    "center_of_mass_velocity_error",
    "semi_amplitude_primary",
    "semi_amplitude_primary_error",
)


def _scalar_text(value: object) -> str:
    if np.ma.is_masked(value):
        return ""
    array = np.asarray(value)
    if array.ndim != 0:
        raise RuntimeError("probe expected a scalar candidate field")
    return str(array.item())


def _safe_error(error: BaseException) -> dict[str, object]:
    message = _LONG_INTEGER.sub("<redacted-id>", str(error))
    return {
        "candidate_safe": True,
        "status": "failure",
        "error_type": type(error).__name__,
        "error_message": message[:500],
        "claim_boundary": "One de-identified Gaia row; no source value is retained.",
    }


def run_probe(gaia_ecsv: Path) -> dict[str, object]:
    table = Table.read(gaia_ecsv, format="ascii.ecsv")
    if len(table) != 1:
        raise RuntimeError(f"expected exactly one Gaia row, received {len(table)}")
    available = {str(name).strip().lower(): str(name) for name in table.colnames}
    missing = sorted(set(_CANDIDATE_FIELDS[1:]) - set(available))
    if missing:
        raise RuntimeError(f"live probe row lacks fields: {missing}")

    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        deidentified = table.copy(copy_data=True)
        deidentified[available["source_id"]][0] = int(_FAKE_SOURCE)
        probe_ecsv = directory / "probe.ecsv"
        deidentified.write(probe_ecsv, format="ascii.ecsv", overwrite=True)

        candidate_csv = directory / "candidate.csv"
        row = table[0]
        candidate: dict[str, str] = {"source_id": _FAKE_SOURCE}
        for field in _CANDIDATE_FIELDS[1:]:
            candidate[field] = _scalar_text(row[available[field]])
        with candidate_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(_CANDIDATE_FIELDS))
            writer.writeheader()
            writer.writerow(candidate)

        enrichment = augment_candidate_covariance_fields(
            gaia_ecsv=probe_ecsv,
            candidate_gaia=candidate_csv,
        )
        with candidate_csv.open("r", encoding="utf-8", newline="") as handle:
            enriched = next(csv.DictReader(handle))
        vector = coerce_correlation_vector(enriched["corr_vec"])
        comparison = compare_with_nsstools(enriched)

    return {
        "candidate_safe": True,
        "status": "success",
        "rows_tested": 1,
        "identity_replaced_before_contract": True,
        "corr_vec_raw_length": int(vector.size),
        "corr_vec_finite_entries": int(np.count_nonzero(np.isfinite(vector))),
        "corr_vec_nonzero_entries": int(
            np.count_nonzero(np.isfinite(vector) & (vector != 0.0))
        ),
        "enrichment_schema_version": enrichment["schema_version"],
        "decoding_mode": comparison.decoding_mode,
        "coefficient_count": comparison.coefficient_count,
        "dpac_parity_max_abs_difference": comparison.maximum_absolute_difference,
        "dpac_parity_exact_within_1e_10": comparison.maximum_absolute_difference <= 1e-10,
        "claim_boundary": "One de-identified Gaia row; no source value is retained.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia_ecsv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run_probe(args.gaia_ecsv)
    except BaseException as error:
        result = _safe_error(error)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(1)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
