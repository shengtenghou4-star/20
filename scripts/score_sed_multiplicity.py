#!/usr/bin/env python3
"""Score one private photometric SED against single and composite templates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from hou_compact.gaia import sha256_file
from hou_compact.sed import compare_single_and_composite_sed


_REQUIRED_KEYS = {"flux", "flux_error", "template_fluxes"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path, help="private NPZ SED/template bundle")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--solution-id", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/sed_evidence.csv"),
    )
    parser.add_argument("--strong-delta-bic", type=float, default=10.0)
    parser.add_argument("--minimum-secondary-flux-fraction", type=float, default=0.05)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with np.load(args.bundle, allow_pickle=False) as bundle:
        missing = sorted(_REQUIRED_KEYS - set(bundle.files))
        if missing:
            raise KeyError(f"SED bundle is missing arrays: {missing}")
        arrays = {key: np.asarray(bundle[key]) for key in _REQUIRED_KEYS}
        labels = None
        if "template_labels" in bundle.files:
            labels = tuple(str(value) for value in bundle["template_labels"].tolist())
        bands = None
        if "band_names" in bundle.files:
            bands = tuple(str(value) for value in bundle["band_names"].tolist())

    evidence = compare_single_and_composite_sed(
        arrays["flux"],
        arrays["flux_error"],
        arrays["template_fluxes"],
        labels,
        strong_delta_bic=args.strong_delta_bic,
        minimum_secondary_flux_fraction=args.minimum_secondary_flux_fraction,
    )
    row = {
        "source_id": args.source_id,
        "solution_id": args.solution_id,
        "sed_evidence_status": evidence.evidence_status,
        "sed_delta_bic_single_minus_composite": (
            evidence.delta_bic_single_minus_composite
        ),
        "sed_secondary_flux_fraction": evidence.secondary_flux_fraction,
        "sed_single_template": evidence.single.template_labels[0],
        "sed_single_bic": evidence.single.bic,
        "sed_composite_template_1": evidence.composite.template_labels[0],
        "sed_composite_template_2": evidence.composite.template_labels[1],
        "sed_composite_bic": evidence.composite.bic,
        "sed_n_bands": evidence.single.n_bands,
        "sed_band_names": ";".join(bands or ()),
        "sed_interpretation_boundary": (
            "Composite-template preference is not a stellar classification. Extinction, "
            "parallax, calibration, photometric variability, and template-grid sensitivity "
            "remain mandatory."
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
        "template_labels": list(labels or ()),
        "band_names": list(bands or ()),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "settings": {
            "strong_delta_bic": args.strong_delta_bic,
            "minimum_secondary_flux_fraction": (
                args.minimum_secondary_flux_fraction
            ),
        },
        "evidence_status": evidence.evidence_status,
        "interpretation_boundary": row["sed_interpretation_boundary"],
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
