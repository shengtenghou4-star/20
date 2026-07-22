#!/usr/bin/env python3
"""Download only exact Gaia/DESI overlap files and extract epochs by TARGETID."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.table import Table

from hou_compact.desi import download_file_bounded
from hou_compact.desi_epoch_columns import restore_single_exposure_columns
from hou_compact.desi_exact import extract_single_epoch_rows_by_targetid
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
    parser.add_argument("gaia", type=Path, help="Gaia seed table")
    parser.add_argument("overlap", type=Path, help="exact Data Lab Gaia/zpix overlap")
    parser.add_argument("availability", type=Path, help="verified DESI file availability table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_epochs_exact.csv"),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/raw/desi_single_epoch_exact"),
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
    if marker not in url:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return cache_dir / f"{digest}.fits"
    relative = url.split(marker, 1)[1]
    return cache_dir / "rv_output" / relative


def _normalize_file_columns(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    missing = sorted(set(_FILE_KEY) - set(frame.columns))
    if missing:
        raise KeyError(f"{name} is missing file-key columns: {missing}")
    result = frame.copy()
    for column in ("survey", "program"):
        result[column] = result[column].astype(str).str.strip().str.lower()
    result["healpix"] = pd.to_numeric(result["healpix"], errors="raise").astype("int64")
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
    overlap = _normalize_file_columns(read_table(args.overlap), "overlap")
    availability = _normalize_file_columns(read_table(args.availability), "availability")
    required_overlap = {"source_id", "targetid", "match_distance_arcsec"}
    missing_overlap = sorted(required_overlap - set(overlap.columns))
    if missing_overlap:
        raise KeyError(f"overlap is missing columns: {missing_overlap}")
    if "source_id" not in gaia.columns:
        raise KeyError("Gaia table has no source_id column")
    overlap["source_id"] = pd.to_numeric(overlap["source_id"], errors="raise").astype("int64")
    overlap["targetid"] = pd.to_numeric(overlap["targetid"], errors="raise").astype("int64")
    overlap["match_distance_arcsec"] = pd.to_numeric(
        overlap["match_distance_arcsec"], errors="raise"
    ).astype(float)
    input_sources = set(pd.to_numeric(gaia["source_id"], errors="raise").astype("int64"))
    unknown_sources = sorted(set(overlap["source_id"]) - input_sources)
    if unknown_sources:
        raise ValueError(f"exact overlap contains source IDs outside Gaia input: {unknown_sources[:5]}")
    if (overlap["match_distance_arcsec"] > 1.5 + 1e-9).any():
        raise ValueError("exact overlap contains a match beyond 1.5 arcsec")

    if "status" in availability.columns:
        availability = availability.loc[
            availability["status"].astype(str).str.lower().isin(["exists", "ok", "200"])
        ]
    if "exists" in availability.columns:
        availability = availability.loc[_truthy(availability["exists"])]
    if "url" not in availability.columns:
        raise KeyError("availability table has no url column")
    if availability.duplicated(_FILE_KEY).any():
        raise ValueError("availability contains duplicate survey/program/healpix rows")

    target_counts = (
        overlap.groupby(_FILE_KEY, as_index=False)
        .agg(exact_target_count=("targetid", "nunique"), exact_source_count=("source_id", "nunique"))
    )
    exact_files = target_counts.merge(
        availability[_FILE_KEY + ["url"]],
        on=_FILE_KEY,
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    missing_files = exact_files.loc[exact_files["_merge"].ne("both"), _FILE_KEY]
    if not missing_files.empty:
        preview = missing_files.head(5).to_dict(orient="records")
        raise ValueError(
            f"{len(missing_files)} exact-overlap files are absent from verified availability: {preview}"
        )
    exact_files = exact_files.drop(columns="_merge").sort_values(
        ["exact_source_count", "exact_target_count", "survey", "program", "healpix"],
        ascending=[False, False, True, True, True],
        kind="stable",
    )
    exact_files = exact_files.head(args.max_files).reset_index(drop=True)

    maximum_file_bytes = int(args.max_file_gb * 1024**3)
    maximum_total_bytes = int(args.max_total_gb * 1024**3)
    total_bytes = 0
    downloads: list[dict[str, object]] = []
    frames: list[pd.DataFrame] = []
    files_with_rows = 0
    for _, file_row in exact_files.iterrows():
        remaining = maximum_total_bytes - total_bytes
        if remaining <= 0:
            break
        key_mask = np.logical_and.reduce(
            [overlap[column].eq(file_row[column]) for column in _FILE_KEY]
        )
        selected_targets = overlap.loc[key_mask].copy()
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
                "survey": str(file_row["survey"]),
                "program": str(file_row["program"]),
                "healpix": int(file_row["healpix"]),
                "exact_target_count": int(file_row["exact_target_count"]),
                "exact_source_count": int(file_row["exact_source_count"]),
            }
        )
        downloads.append(result)
        extracted = extract_single_epoch_rows_by_targetid(
            local,
            selected_targets,
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
        epochs = pd.DataFrame(
            columns=[
                "source_id",
                "targetid",
                "expid",
                "mjd",
                "vrad",
                "vrad_err",
                "success",
                "rvs_warn",
                "fiberstatus",
                "sn_b",
                "sn_r",
                "sn_z",
                "survey",
                "program",
                "healpix",
                "source_match_mode",
                "source_match_separation_arcsec",
                "desi_ref_id",
                "desi_ref_cat",
                "official_epoch_columns_restored",
            ]
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    epochs.to_csv(args.output, index=False)
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "exact_overlap_input": str(args.overlap),
        "exact_overlap_input_sha256": sha256_file(args.overlap),
        "availability_input": str(args.availability),
        "availability_input_sha256": sha256_file(args.availability),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "exact_overlap_rows": len(overlap),
        "exact_overlap_source_count": int(overlap["source_id"].nunique()),
        "exact_overlap_target_count": int(overlap["targetid"].nunique()),
        "exact_overlap_file_count": len(target_counts),
        "files_selected": len(exact_files),
        "files_downloaded": len(downloads),
        "files_with_matched_rows": files_with_rows,
        "downloaded_bytes": total_bytes,
        "output_rows": len(epochs),
        "matched_source_count": (
            int(epochs["source_id"].nunique()) if not epochs.empty else 0
        ),
        "matched_target_count": (
            int(epochs["targetid"].nunique()) if not epochs.empty else 0
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
            "Rows are extracted by exact DESI TARGETID from the official Data Lab Gaia/zpix "
            "crossmatch. They remain measurements, not orbit support or compact-object labels."
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
