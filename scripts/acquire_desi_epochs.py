#!/usr/bin/env python3
"""Download selected DESI single-epoch files and extract Gaia-matched RV rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.desi import (
    download_file_bounded,
    extract_single_epoch_rows,
    source_id_to_healpix,
)
from hou_compact.desi_epoch_columns import restore_single_exposure_columns
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
    parser.add_argument("gaia", type=Path, help="Gaia seed table")
    parser.add_argument("probe", type=Path, help="DESI file probe table")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/desi_epochs.csv"),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/raw/desi_single_epoch"),
    )
    parser.add_argument("--max-files", type=int, default=32)
    parser.add_argument("--max-file-gb", type=float, default=3.0)
    parser.add_argument("--max-total-gb", type=float, default=20.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--maximum-match-separation-arcsec", type=float, default=1.0)
    parser.add_argument("--minimum-ambiguity-margin-arcsec", type=float, default=0.1)
    parser.add_argument("--remove-fits-after-extraction", action="store_true")
    return parser.parse_args()


def _local_path(cache_dir: Path, url: str) -> Path:
    marker = "/rv_output/"
    if marker not in url:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return cache_dir / f"{digest}.fits"
    relative = url.split(marker, 1)[1]
    return cache_dir / "rv_output" / relative


def _truthy(series: pd.Series) -> pd.Series:
    """Parse persisted boolean columns without treating the string 'False' as true."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def main() -> None:
    args = parse_args()
    if args.max_files < 1:
        raise ValueError("max_files must be positive")
    if args.max_file_gb <= 0 or args.max_total_gb <= 0:
        raise ValueError("download size limits must be positive")
    if args.maximum_match_separation_arcsec <= 0:
        raise ValueError("maximum_match_separation_arcsec must be positive")
    if args.minimum_ambiguity_margin_arcsec < 0:
        raise ValueError("minimum_ambiguity_margin_arcsec must be non-negative")
    maximum_file_bytes = int(args.max_file_gb * 1024**3)
    maximum_total_bytes = int(args.max_total_gb * 1024**3)

    gaia = read_table(args.gaia)
    probe = read_table(args.probe)
    required_gaia = {"source_id", "gaia_ra", "gaia_dec"}
    missing_gaia = sorted(required_gaia - set(gaia.columns))
    if missing_gaia:
        raise KeyError(f"Gaia input is missing columns: {missing_gaia}")
    required_probe = {"url", "survey", "program", "healpix"}
    missing_probe = sorted(required_probe - set(probe.columns))
    if missing_probe:
        raise KeyError(f"probe table is missing columns: {missing_probe}")
    if "status" in probe.columns:
        probe = probe.loc[probe["status"].astype(str).str.lower().isin(["exists", "ok", "200"])]
    if "exists" in probe.columns:
        probe = probe.loc[_truthy(probe["exists"])]
    if "bytes" in probe.columns:
        numeric_bytes = pd.to_numeric(probe["bytes"], errors="coerce")
        probe = probe.loc[numeric_bytes.isna() | numeric_bytes.le(maximum_file_bytes)]
    probe = probe.head(args.max_files).reset_index(drop=True)

    gaia = gaia.copy()
    gaia["_desi_healpix"] = gaia["source_id"].map(
        lambda value: source_id_to_healpix(int(value), level=6)
    )
    records: list[pd.DataFrame] = []
    downloads: list[dict[str, object]] = []
    total_bytes = 0
    files_with_matched_rows = 0
    for _, item in probe.iterrows():
        url = str(item["url"])
        local = _local_path(args.cache_dir, url)
        remaining = maximum_total_bytes - total_bytes
        if remaining <= 0:
            break
        result = download_file_bounded(
            url,
            local,
            maximum_bytes=min(maximum_file_bytes, remaining),
            timeout=args.timeout,
            retries=args.retries,
        )
        total_bytes += int(result["bytes"])
        downloads.append(result)
        file_healpix = int(item["healpix"])
        selected_sources = gaia.loc[gaia["_desi_healpix"].eq(file_healpix)].drop(
            columns=["_desi_healpix"]
        )
        extracted = extract_single_epoch_rows(
            local,
            selected_sources,
            survey=str(item["survey"]),
            program=str(item["program"]),
            healpix=file_healpix,
            maximum_match_separation_arcsec=args.maximum_match_separation_arcsec,
            minimum_ambiguity_margin_arcsec=args.minimum_ambiguity_margin_arcsec,
        )
        extracted = restore_single_exposure_columns(local, extracted)
        if not extracted.empty:
            files_with_matched_rows += 1
            records.append(extracted)
        if args.remove_fits_after_extraction:
            local.unlink(missing_ok=True)

    if records:
        epochs = pd.concat(records, ignore_index=True)
        epochs = epochs.sort_values(
            ["source_id", "mjd", "expid"], kind="stable"
        ).reset_index(drop=True)
    else:
        epochs = pd.DataFrame(
            columns=[
                "source_id",
                "targetid",
                "expid",
                "mjd",
                "night",
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
    matched_source_count = (
        int(epochs["source_id"].nunique()) if "source_id" in epochs.columns else 0
    )
    finite_separations = pd.to_numeric(
        epochs.get("source_match_separation_arcsec", pd.Series(dtype=float)),
        errors="coerce",
    )
    finite_separations = finite_separations.loc[finite_separations.map(math.isfinite)]
    restored_rows = (
        int(_truthy(epochs["official_epoch_columns_restored"]).sum())
        if "official_epoch_columns_restored" in epochs.columns
        else 0
    )
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "probe_input": str(args.probe),
        "probe_input_sha256": sha256_file(args.probe),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "files_selected": len(probe),
        "files_downloaded": len(downloads),
        "files_with_matched_rows": files_with_matched_rows,
        "downloaded_bytes": total_bytes,
        "output_rows": len(epochs),
        "matched_source_count": matched_source_count,
        "official_epoch_columns_restored_rows": restored_rows,
        "match_mode_counts": (
            {
                str(key): int(value)
                for key, value in epochs["source_match_mode"].value_counts().items()
            }
            if "source_match_mode" in epochs.columns
            else {}
        ),
        "maximum_matched_separation_arcsec": (
            float(finite_separations.max()) if len(finite_separations) else None
        ),
        "settings": {
            "max_files": args.max_files,
            "max_file_gb": args.max_file_gb,
            "max_total_gb": args.max_total_gb,
            "timeout": args.timeout,
            "retries": args.retries,
            "maximum_match_separation_arcsec": args.maximum_match_separation_arcsec,
            "minimum_ambiguity_margin_arcsec": args.minimum_ambiguity_margin_arcsec,
            "remove_fits_after_extraction": args.remove_fits_after_extraction,
        },
        "downloads": downloads,
        "interpretation_boundary": (
            "Rows are Gaia DR3 matches to DESI per-exposure RV products. MJD/NIGHT are "
            "restored from FIBERMAP and SN_B/SN_R/SN_Z from RVTAB before downstream "
            "quality and duplicate audits."
        ),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
