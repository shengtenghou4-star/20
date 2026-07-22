#!/usr/bin/env python3
"""Recover DESI MWS epochs using Gaia DR2 REF_ID metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.table import Table

from hou_compact.desi import download_file_bounded, gaia_source_id_to_healpix
from hou_compact.desi_epoch_columns import restore_single_exposure_columns
from hou_compact.desi_exact import extract_single_epoch_rows_by_dr2_refid
from hou_compact.gaia import sha256_file

_FILE_KEY = ["survey", "program", "healpix"]


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path)
    parser.add_argument("bridge", type=Path, help="audited Gaia DR3-to-DR2 bridge")
    parser.add_argument("availability", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_epochs_refid.csv"),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/raw/desi_single_epoch_refid"),
    )
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--max-file-gb", type=float, default=1.0)
    parser.add_argument("--max-total-gb", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--remove-fits-after-extraction", action="store_true")
    return parser.parse_args()


def _truthy(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _local_path(cache_dir: Path, url: str) -> Path:
    marker = "/rv_output/"
    if marker in url:
        return cache_dir / "rv_output" / url.split(marker, 1)[1]
    return cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.fits"


def _normalize_availability(frame: pd.DataFrame) -> pd.DataFrame:
    required = set(_FILE_KEY + ["url"])
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"availability is missing columns: {missing}")
    result = frame.copy()
    for column in ("survey", "program"):
        result[column] = result[column].astype(str).str.strip().str.lower()
    result["healpix"] = pd.to_numeric(result["healpix"], errors="raise").astype("int64")
    if "status" in result.columns:
        result = result.loc[
            result["status"].astype(str).str.lower().isin({"exists", "ok", "200"})
        ]
    if "exists" in result.columns:
        result = result.loc[_truthy(result["exists"])]
    if result.duplicated(_FILE_KEY).any():
        raise ValueError("availability contains duplicate file-key rows")
    return result


def main() -> None:
    args = parse_args()
    if args.max_files < 1:
        raise ValueError("max_files must be positive")
    if args.max_file_gb <= 0 or args.max_total_gb <= 0:
        raise ValueError("download size limits must be positive")
    if args.timeout <= 0 or args.retries < 0:
        raise ValueError("timeout/retry settings are invalid")

    gaia = read_table(args.gaia)
    bridge = read_table(args.bridge)
    availability = _normalize_availability(read_table(args.availability))
    if "source_id" not in gaia.columns:
        raise KeyError("Gaia input has no source_id column")
    required_bridge = {
        "source_id",
        "dr2_source_id",
        "dr2_bridge_status",
        "dr2_angular_distance_mas",
        "dr2_neighbour_count",
        "dr2_distance_margin_mas",
    }
    missing_bridge = sorted(required_bridge - set(bridge.columns))
    if missing_bridge:
        raise KeyError(f"bridge is missing columns: {missing_bridge}")

    gaia_ids = pd.to_numeric(gaia["source_id"], errors="raise").astype("int64")
    if gaia_ids.duplicated().any():
        raise ValueError("Gaia input contains duplicate source_id rows")
    bridge = bridge.copy()
    bridge["source_id"] = pd.to_numeric(bridge["source_id"], errors="raise").astype("int64")
    unknown = sorted(set(bridge["source_id"]) - set(gaia_ids))
    if unknown:
        raise ValueError(f"bridge contains sources outside Gaia input: {unknown[:5]}")
    bridge = bridge.loc[
        bridge["dr2_bridge_status"].eq("accepted_unique_or_separated_nearest")
    ].copy()
    bridge["healpix"] = [
        gaia_source_id_to_healpix(int(value)) for value in bridge["source_id"]
    ]

    file_counts = (
        bridge.groupby("healpix", as_index=False)
        .agg(bridge_source_count=("source_id", "nunique"))
    )
    candidate_files = availability.merge(
        file_counts,
        on="healpix",
        how="inner",
        validate="many_to_one",
    )
    candidate_files = candidate_files.loc[
        candidate_files["program"].isin({"bright", "dark"})
    ].sort_values(
        ["bridge_source_count", "survey", "program", "healpix"],
        ascending=[False, True, True, True],
        kind="stable",
    )
    candidate_files = candidate_files.head(args.max_files).reset_index(drop=True)

    maximum_file_bytes = int(args.max_file_gb * 1024**3)
    maximum_total_bytes = int(args.max_total_gb * 1024**3)
    total_bytes = 0
    downloads: list[dict[str, object]] = []
    frames: list[pd.DataFrame] = []
    files_with_rows = 0
    for _, file_row in candidate_files.iterrows():
        remaining = maximum_total_bytes - total_bytes
        if remaining <= 0:
            break
        selected_bridge = bridge.loc[bridge["healpix"].eq(int(file_row["healpix"]))]
        url = str(file_row["url"])
        local = _local_path(args.cache_dir, url)
        result = download_file_bounded(
            url,
            local,
            maximum_bytes=min(maximum_file_bytes, remaining),
            timeout=args.timeout,
            retries=args.retries,
        )
        total_bytes += int(result["bytes"])
        result.update(
            {
                "sha256": sha256_file(local),
                "survey": str(file_row["survey"]),
                "program": str(file_row["program"]),
                "healpix": int(file_row["healpix"]),
                "bridge_source_count": int(file_row["bridge_source_count"]),
            }
        )
        downloads.append(result)
        extracted = extract_single_epoch_rows_by_dr2_refid(
            local,
            selected_bridge,
            survey=str(file_row["survey"]),
            program=str(file_row["program"]),
            healpix=int(file_row["healpix"]),
        )
        extracted = restore_single_exposure_columns(local, extracted)
        if not extracted.empty:
            files_with_rows += 1
            frames.append(extracted)
        if args.remove_fits_after_extraction:
            local.unlink(missing_ok=True)

    if frames:
        epochs = pd.concat(frames, ignore_index=True)
        duplicate_key = ["source_id", "targetid", "expid", "survey", "program"]
        epochs = epochs.drop_duplicates(duplicate_key).sort_values(
            ["source_id", "mjd", "expid"], kind="stable", na_position="last"
        ).reset_index(drop=True)
    else:
        epochs = pd.DataFrame()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    epochs.to_csv(args.output, index=False)
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "bridge_input": str(args.bridge),
        "bridge_input_sha256": sha256_file(args.bridge),
        "availability_input": str(args.availability),
        "availability_input_sha256": sha256_file(args.availability),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "accepted_bridge_source_count": int(bridge["source_id"].nunique()),
        "candidate_file_count": len(candidate_files),
        "files_downloaded": len(downloads),
        "files_with_matched_rows": files_with_rows,
        "downloaded_bytes": total_bytes,
        "output_rows": len(epochs),
        "matched_source_count": (
            int(epochs["source_id"].nunique()) if not epochs.empty else 0
        ),
        "match_mode_counts": (
            {
                str(key): int(value)
                for key, value in epochs["source_match_mode"].value_counts().items()
            }
            if not epochs.empty
            else {}
        ),
        "settings": {
            "max_files": args.max_files,
            "max_file_gb": args.max_file_gb,
            "max_total_gb": args.max_total_gb,
            "timeout": args.timeout,
            "retries": args.retries,
            "remove_fits_after_extraction": args.remove_fits_after_extraction,
        },
        "downloads": downloads,
        "interpretation_boundary": (
            "Rows require an accepted Gaia DR3-to-DR2 neighbourhood bridge and exact "
            "DESI FIBERMAP REF_CAT='G2'/REF_ID equality. They remain measurements, not "
            "orbit support or compact-object classifications."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
