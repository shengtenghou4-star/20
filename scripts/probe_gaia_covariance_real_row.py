#!/usr/bin/env python3
"""Run the production enrichment/parity sequence on one de-identified live Gaia row."""

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

from gaia_candidate_vetting import augment_candidate_gaia  # noqa: E402
from gaia_covariance_enrichment import augment_candidate_covariance_fields  # noqa: E402
from hou_compact.gaia_covariance import coerce_correlation_vector  # noqa: E402
from hou_compact.reference_covariance import compare_with_nsstools  # noqa: E402

_FAKE_SOURCE = "1234567890123456789"
_LONG_INTEGER = re.compile(r"(?<![0-9])[0-9]{10,20}(?![0-9])")
_PRODUCTION_CANDIDATE_FIELDS = (
    "source_id",
    "nss_solution_type",
    "period",
    "gaia_ref_epoch",
    "t_periastron",
    "eccentricity",
    "arg_periastron",
    "semi_amplitude_primary",
    "mass_flame",
    "mass_flame_lower",
    "mass_flame_upper",
    "flags_flame",
)
_LIVE_SCALAR_FIELDS = (
    "nss_solution_type",
    "period",
    "t_periastron",
    "eccentricity",
    "arg_periastron",
    "semi_amplitude_primary",
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
    missing = sorted(set(_LIVE_SCALAR_FIELDS) - set(available))
    if missing:
        raise RuntimeError(f"live probe row lacks fields: {missing}")

    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        deidentified = table.copy(copy_data=True)
        deidentified[available["source_id"]][0] = int(_FAKE_SOURCE)
        probe_ecsv = directory / "probe.ecsv"
        deidentified.write(probe_ecsv, format="ascii.ecsv", overwrite=True)

        # Reproduce the exact sparse candidate table emitted by
        # phase_followup_pipeline.prepare_candidates before either post-command hook runs.
        row = table[0]
        candidate: dict[str, str] = {
            "source_id": _FAKE_SOURCE,
            "gaia_ref_epoch": "2016.0",
            "mass_flame": "1.0",
            "mass_flame_lower": "0.9",
            "mass_flame_upper": "1.1",
            "flags_flame": "0",
        }
        for field in _LIVE_SCALAR_FIELDS:
            candidate[field] = _scalar_text(row[available[field]])

        candidate_csv = directory / "candidate.csv"
        with candidate_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(_PRODUCTION_CANDIDATE_FIELDS),
                extrasaction="raise",
            )
            writer.writeheader()
            writer.writerow(candidate)

        quality_enrichment = augment_candidate_gaia(
            gaia_ecsv=probe_ecsv,
            candidate_gaia=candidate_csv,
        )
        covariance_enrichment = augment_candidate_covariance_fields(
            gaia_ecsv=probe_ecsv,
            candidate_gaia=candidate_csv,
        )
        with candidate_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            final_fields = list(reader.fieldnames or [])
            enriched = next(reader)
        vector = coerce_correlation_vector(enriched["corr_vec"])
        comparison = compare_with_nsstools(enriched)

    expected_appended = {
        "period_error",
        "eccentricity_error",
        "semi_amplitude_primary_error",
        "bit_index",
        "corr_vec",
        "center_of_mass_velocity",
        "center_of_mass_velocity_error",
        "t_periastron_error",
        "arg_periastron_error",
    }
    missing_after_enrichment = sorted(expected_appended - set(final_fields))
    if missing_after_enrichment:
        raise RuntimeError(
            f"production enrichment sequence omitted fields: {missing_after_enrichment}"
        )

    return {
        "candidate_safe": True,
        "status": "success",
        "rows_tested": 1,
        "identity_replaced_before_contract": True,
        "exact_sparse_production_schema_reproduced": True,
        "production_enrichment_order_reproduced": True,
        "solution_type": str(enriched["nss_solution_type"]),
        "initial_field_count": len(_PRODUCTION_CANDIDATE_FIELDS),
        "final_field_count": len(final_fields),
        "corr_vec_raw_length": int(vector.size),
        "corr_vec_finite_entries": int(np.count_nonzero(np.isfinite(vector))),
        "corr_vec_nonzero_entries": int(
            np.count_nonzero(np.isfinite(vector) & (vector != 0.0))
        ),
        "quality_fields_appended": int(quality_enrichment["fields_appended"]),
        "covariance_enrichment_schema_version": covariance_enrichment["schema_version"],
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
