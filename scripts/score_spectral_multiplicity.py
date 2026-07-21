#!/usr/bin/env python3
"""Score one private spectrum against one- and two-velocity template models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from hou_compact.gaia import sha256_file
from hou_compact.spectral import compare_single_and_double_templates


_REQUIRED_KEYS = {
    "wavelength",
    "flux",
    "inverse_variance",
    "template_wavelength",
    "template_flux",
    "velocity_grid_kms",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path, help="private NPZ spectral/template bundle")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--solution-id", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/spectral_evidence.csv"),
    )
    parser.add_argument("--minimum-separation-kms", type=float, default=40.0)
    parser.add_argument("--strong-delta-bic", type=float, default=10.0)
    parser.add_argument("--minimum-secondary-ratio", type=float, default=0.10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with np.load(args.bundle, allow_pickle=False) as bundle:
        missing = sorted(_REQUIRED_KEYS - set(bundle.files))
        if missing:
            raise KeyError(f"spectral bundle is missing arrays: {missing}")
        arrays = {key: np.asarray(bundle[key]) for key in _REQUIRED_KEYS}

    evidence = compare_single_and_double_templates(
        arrays["wavelength"],
        arrays["flux"],
        arrays["inverse_variance"],
        arrays["template_wavelength"],
        arrays["template_flux"],
        arrays["velocity_grid_kms"],
        minimum_separation_kms=args.minimum_separation_kms,
        strong_delta_bic=args.strong_delta_bic,
        minimum_secondary_ratio=args.minimum_secondary_ratio,
    )
    row = {
        "source_id": args.source_id,
        "solution_id": args.solution_id,
        "spectral_evidence_status": evidence.evidence_status,
        "spectral_delta_bic_single_minus_double": (
            evidence.delta_bic_single_minus_double
        ),
        "spectral_velocity_separation_kms": evidence.velocity_separation_kms,
        "spectral_secondary_to_primary_amplitude": (
            evidence.secondary_to_primary_amplitude
        ),
        "spectral_single_velocity_kms": evidence.single.velocities_kms[0],
        "spectral_single_bic": evidence.single.bic,
        "spectral_double_velocity_1_kms": evidence.double.velocities_kms[0],
        "spectral_double_velocity_2_kms": evidence.double.velocities_kms[1],
        "spectral_double_bic": evidence.double.bic,
        "spectral_n_pixels": evidence.single.n_pixels,
        "spectral_interpretation_boundary": (
            "Template-grid multiplicity evidence is not a stellar classification. "
            "Template-library, wavelength-region, continuum, and calibration sensitivity "
            "tests remain mandatory."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(args.output, index=False)
    manifest = {
        "bundle": str(args.bundle),
        "bundle_sha256": sha256_file(args.bundle),
        "bundle_arrays": {
            key: list(value.shape) for key, value in arrays.items()
        },
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "settings": {
            "minimum_separation_kms": args.minimum_separation_kms,
            "strong_delta_bic": args.strong_delta_bic,
            "minimum_secondary_ratio": args.minimum_secondary_ratio,
        },
        "evidence_status": evidence.evidence_status,
        "interpretation_boundary": row["spectral_interpretation_boundary"],
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
