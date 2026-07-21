#!/usr/bin/env python3
"""Generate Gaia-side WP5 contamination evidence for a seed catalogue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.contamination import ContaminationConfig, audit_gaia_contamination
from hou_compact.gaia import sha256_file


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path, help="Gaia v5 SB1/SB1C seed table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/gaia_contamination_audit.csv"),
    )
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--ipd-multi-peak-percent", type=float, default=2.0)
    parser.add_argument("--ipd-odd-window-percent", type=float, default=5.0)
    parser.add_argument("--ipd-harmonic-amplitude", type=float, default=0.1)
    parser.add_argument("--excess-noise-significance", type=float, default=2.0)
    parser.add_argument("--blended-transit-fraction", type=float, default=0.05)
    parser.add_argument("--contaminated-transit-fraction", type=float, default=0.05)
    parser.add_argument("--deblended-rv-fraction", type=float, default=0.10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_rows < 1:
        raise ValueError("max_rows must be positive")
    gaia = read_table(args.gaia)
    required = {"source_id", "solution_id", "nss_solution_type"}
    missing = sorted(required - set(gaia.columns))
    if missing:
        raise KeyError(f"Gaia input is missing columns: {missing}")
    if gaia.duplicated(["source_id", "solution_id"]).any():
        raise ValueError("Gaia input contains duplicate source/solution rows")

    config = ContaminationConfig(
        ipd_multi_peak_percent_caution=args.ipd_multi_peak_percent,
        ipd_odd_window_percent_caution=args.ipd_odd_window_percent,
        ipd_harmonic_amplitude_caution=args.ipd_harmonic_amplitude,
        astrometric_excess_noise_significance_caution=(
            args.excess_noise_significance
        ),
        blended_transit_fraction_caution=args.blended_transit_fraction,
        contaminated_transit_fraction_caution=(
            args.contaminated_transit_fraction
        ),
        deblended_rv_fraction_caution=args.deblended_rv_fraction,
    )
    rows = gaia.head(args.max_rows).copy()
    audit = pd.DataFrame(
        [audit_gaia_contamination(row, config) for row in rows.to_dict(orient="records")]
    )
    output = pd.concat(
        [
            rows[["source_id", "solution_id", "nss_solution_type"]].reset_index(
                drop=True
            ),
            audit,
        ],
        axis=1,
    )
    output = output.sort_values(
        ["gaia_contamination_signal_count", "source_id"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    status_counts = {
        str(key): int(value)
        for key, value in output["gaia_contamination_status"].value_counts().items()
    }
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "input_rows": len(gaia),
        "rows_attempted": len(rows),
        "output_rows": len(output),
        "status_counts": status_counts,
        "thresholds": {
            "ipd_multi_peak_percent_caution": (
                config.ipd_multi_peak_percent_caution
            ),
            "ipd_odd_window_percent_caution": (
                config.ipd_odd_window_percent_caution
            ),
            "ipd_harmonic_amplitude_caution": (
                config.ipd_harmonic_amplitude_caution
            ),
            "astrometric_excess_noise_significance_caution": (
                config.astrometric_excess_noise_significance_caution
            ),
            "blended_transit_fraction_caution": (
                config.blended_transit_fraction_caution
            ),
            "contaminated_transit_fraction_caution": (
                config.contaminated_transit_fraction_caution
            ),
            "deblended_rv_fraction_caution": (
                config.deblended_rv_fraction_caution
            ),
        },
        "interpretation_boundary": (
            "This table records Gaia-side contamination evidence. It neither confirms "
            "nor excludes a luminous companion or compact object."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
