#!/usr/bin/env python3
"""Extract exact Gaia-bridged LAMOST DR8 v1.0 multi-epoch rows in chunks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from hou_compact.gaia import sha256_file
from hou_compact.lamost import (
    LamostContractError,
    explode_lrs_multiple_epoch_catalog,
    join_lrs_spectrum_uncertainties,
    parse_exact_int_text,
)

_MULTIPLE_COLUMNS = [
    "source_id",
    "gaia_source_id",
    "obs_number",
    "obsid_list",
    "midmjm_list",
    "rv_list",
]
_SPECTRUM_REQUIRED = ["obsid", "rv", "rv_err"]
_SPECTRUM_OPTIONAL = ["snrg", "snri", "class", "subclass", "fibermask"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("multiple_epoch_csv", type=Path)
    parser.add_argument("bridge_csv", type=Path)
    parser.add_argument(
        "--spectrum-catalog",
        type=Path,
        action="append",
        default=[],
        help=(
            "repeat for AFGK/A/M per-spectrum catalogues containing "
            "obsid, rv, rv_err"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/lamost_dr8_epochs.csv"),
    )
    parser.add_argument("--chunk-size", type=int, default=100_000)
    parser.add_argument("--maximum-rv-difference-kms", type=float, default=1.0)
    return parser.parse_args()


def _accepted_bridge(path: Path) -> tuple[dict[int, int], dict[str, int]]:
    bridge = pd.read_csv(path, dtype=str)
    required = {"source_id", "dr2_source_id", "dr2_bridge_status"}
    missing = sorted(required - set(bridge.columns))
    if missing:
        raise KeyError(f"bridge is missing columns: {missing}")
    accepted = bridge.loc[
        bridge["dr2_bridge_status"].eq(
            "accepted_unique_or_separated_nearest"
        )
    ].copy()
    accepted["source_id_int"] = [
        parse_exact_int_text(value, name="bridge.source_id")
        for value in accepted["source_id"]
    ]
    accepted["dr2_source_id_int"] = [
        parse_exact_int_text(value, name="bridge.dr2_source_id")
        for value in accepted["dr2_source_id"]
    ]
    if accepted["source_id_int"].duplicated().any():
        raise LamostContractError(
            "accepted bridge contains duplicate Gaia DR3 source IDs"
        )
    if accepted["dr2_source_id_int"].duplicated().any():
        raise LamostContractError(
            "accepted bridge maps one Gaia DR2 ID to multiple Gaia DR3 sources"
        )
    mapping = dict(
        zip(
            accepted["dr2_source_id_int"].astype(int),
            accepted["source_id_int"].astype(int),
            strict=True,
        )
    )
    status_counts = {
        str(key): int(value)
        for key, value in bridge["dr2_bridge_status"].value_counts().items()
    }
    return mapping, status_counts


def _normalized_identifier_text(
    series: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    raw = series.astype("string").fillna("").str.strip()
    normalized = raw.str.replace(
        r"[.]0+$",
        "",
        regex=True,
    ).str.removeprefix("+")
    valid = normalized.str.fullmatch(r"[0-9]+")
    return normalized, valid


def _scan_multiple_epoch_catalog(
    path: Path,
    dr2_to_dr3: dict[int, int],
    *,
    chunk_size: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    targets = {str(value) for value in dr2_to_dr3}
    frames: list[pd.DataFrame] = []
    rows_scanned = 0
    rows_with_invalid_identifier_text = 0
    matched_catalogue_rows = 0
    contract_failures = 0

    for chunk in pd.read_csv(
        path,
        dtype=str,
        usecols=_MULTIPLE_COLUMNS,
        chunksize=chunk_size,
    ):
        rows_scanned += len(chunk)
        normalized, valid = _normalized_identifier_text(
            chunk["gaia_source_id"]
        )
        invalid_nonempty = ~valid & normalized.ne("")
        rows_with_invalid_identifier_text += int(invalid_nonempty.sum())
        selected = chunk.loc[valid & normalized.isin(targets)].copy()
        if selected.empty:
            continue
        selected["gaia_source_id"] = normalized.loc[selected.index]
        matched_catalogue_rows += len(selected)
        for row in selected.to_dict(orient="records"):
            try:
                epochs = explode_lrs_multiple_epoch_catalog([row])
            except (LamostContractError, KeyError, TypeError, ValueError):
                contract_failures += 1
                continue
            epochs["source_id"] = epochs["dr2_source_id"].map(dr2_to_dr3)
            if epochs["source_id"].isna().any():
                raise RuntimeError(
                    "matched LAMOST DR2 ID is absent from frozen bridge map"
                )
            epochs["source_id"] = epochs["source_id"].astype("int64")
            frames.append(epochs)

    if frames:
        output = pd.concat(frames, ignore_index=True)
        duplicate = output.duplicated(["source_id", "obsid"])
        if duplicate.any():
            duplicate_count = int(duplicate.sum())
            raise LamostContractError(
                "extracted overlap contains "
                f"{duplicate_count} duplicate source/obsid rows"
            )
        output = output.sort_values(
            ["source_id", "mjd", "obsid"],
            kind="stable",
        ).reset_index(drop=True)
    else:
        output = pd.DataFrame()
    summary = {
        "multiple_epoch_rows_scanned": rows_scanned,
        "rows_with_invalid_identifier_text": (
            rows_with_invalid_identifier_text
        ),
        "matched_catalogue_rows": matched_catalogue_rows,
        "contract_failure_rows": contract_failures,
        "exploded_epoch_rows": len(output),
        "matched_gaia_dr3_sources": (
            int(output["source_id"].nunique()) if not output.empty else 0
        ),
    }
    return output, summary


def _scan_spectrum_catalogs(
    paths: list[Path],
    obsids: set[int],
    *,
    chunk_size: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if not paths or not obsids:
        return pd.DataFrame(columns=_SPECTRUM_REQUIRED), {
            "catalogues_scanned": len(paths),
            "rows_scanned": 0,
            "matched_spectrum_rows": 0,
        }
    targets = {str(value) for value in obsids}
    frames: list[pd.DataFrame] = []
    rows_scanned = 0
    per_catalogue: list[dict[str, object]] = []
    for path in paths:
        header = pd.read_csv(path, nrows=0).columns.tolist()
        missing = sorted(set(_SPECTRUM_REQUIRED) - set(header))
        if missing:
            raise KeyError(f"{path} is missing spectrum columns: {missing}")
        usecols = _SPECTRUM_REQUIRED + [
            column for column in _SPECTRUM_OPTIONAL if column in header
        ]
        catalogue_rows = 0
        catalogue_matches = 0
        for chunk in pd.read_csv(
            path,
            dtype=str,
            usecols=usecols,
            chunksize=chunk_size,
        ):
            rows_scanned += len(chunk)
            catalogue_rows += len(chunk)
            normalized, valid = _normalized_identifier_text(chunk["obsid"])
            selected = chunk.loc[valid & normalized.isin(targets)].copy()
            if selected.empty:
                continue
            selected["obsid"] = normalized.loc[selected.index]
            catalogue_matches += len(selected)
            frames.append(selected)
        per_catalogue.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "rows_scanned": catalogue_rows,
                "matched_rows": catalogue_matches,
            }
        )
    spectra = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=_SPECTRUM_REQUIRED)
    )
    if not spectra.empty:
        parsed_obsids = [
            parse_exact_int_text(value, name="spectrum.obsid")
            for value in spectra["obsid"]
        ]
        if pd.Series(parsed_obsids).duplicated().any():
            raise LamostContractError(
                "per-spectrum catalogues contain duplicate matched obsid rows"
            )
    return spectra, {
        "catalogues_scanned": len(paths),
        "rows_scanned": rows_scanned,
        "matched_spectrum_rows": len(spectra),
        "per_catalogue": per_catalogue,
    }


def _numeric_or_nan(
    frame: pd.DataFrame,
    column: str,
) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _standardize_for_orbit(joined: pd.DataFrame) -> pd.DataFrame:
    if joined.empty:
        return joined
    output = joined.copy()
    output["success"] = output["lamost_epoch_status"].eq("scorable")
    output["rvs_warn"] = np.where(output["success"], 0, 1)
    if "fibermask" in output.columns:
        fiber = pd.to_numeric(output["fibermask"], errors="coerce")
        output["fiberstatus"] = fiber.fillna(1).astype("int64")
        output.loc[output["fiberstatus"].ne(0), "success"] = False
        output.loc[output["fiberstatus"].ne(0), "rvs_warn"] = 1
    else:
        output["fiberstatus"] = 1
        output["success"] = False
        output["rvs_warn"] = 1
        output["lamost_epoch_status"] = "missing_fibermask"
    output["sn_b"] = _numeric_or_nan(output, "snrg")
    output["sn_r"] = _numeric_or_nan(output, "snri")
    output["sn_z"] = np.nan
    output["program"] = "lamost_lrs_dr8_v1"
    output["expid"] = output["obsid"]
    return output


def main() -> None:
    args = parse_args()
    if args.chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    dr2_to_dr3, bridge_status_counts = _accepted_bridge(args.bridge_csv)
    epochs, multiple_summary = _scan_multiple_epoch_catalog(
        args.multiple_epoch_csv,
        dr2_to_dr3,
        chunk_size=args.chunk_size,
    )

    spectrum_summary: dict[str, object] = {
        "catalogues_scanned": 0,
        "rows_scanned": 0,
        "matched_spectrum_rows": 0,
    }
    if args.spectrum_catalog and not epochs.empty:
        spectra, spectrum_summary = _scan_spectrum_catalogs(
            args.spectrum_catalog,
            set(epochs["obsid"].astype(int)),
            chunk_size=args.chunk_size,
        )
        epochs = join_lrs_spectrum_uncertainties(
            epochs,
            spectra,
            maximum_rv_difference_kms=(
                args.maximum_rv_difference_kms
            ),
        )
        epochs = _standardize_for_orbit(epochs)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    epochs.to_csv(args.output, index=False)
    status_counts = (
        {
            str(key): int(value)
            for key, value in epochs["lamost_epoch_status"].value_counts().items()
        }
        if "lamost_epoch_status" in epochs.columns
        else {}
    )
    manifest = {
        "multiple_epoch_catalog": {
            "path": str(args.multiple_epoch_csv),
            "sha256": sha256_file(args.multiple_epoch_csv),
        },
        "bridge": {
            "path": str(args.bridge_csv),
            "sha256": sha256_file(args.bridge_csv),
            "accepted_source_count": len(dr2_to_dr3),
            "status_counts": bridge_status_counts,
        },
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "output_rows": len(epochs),
        "output_gaia_dr3_sources": (
            int(epochs["source_id"].nunique()) if not epochs.empty else 0
        ),
        "epoch_status_counts": status_counts,
        "multiple_epoch_scan": multiple_summary,
        "spectrum_scan": spectrum_summary,
        "settings": {
            "chunk_size": args.chunk_size,
            "maximum_rv_difference_kms": (
                args.maximum_rv_difference_kms
            ),
        },
        "interpretation_boundary": (
            "Exact Gaia DR2 overlap and repeated LAMOST measurements do not "
            "establish Gaia-orbit support or a compact-object classification."
        ),
    }
    manifest_path = args.output.with_suffix(
        args.output.suffix + ".manifest.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
