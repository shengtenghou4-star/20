#!/usr/bin/env python3
"""Download only confirmed DESI files and extract Gaia-matched epoch rows safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
from astropy.table import Table

from hou_compact.desi import extract_single_epoch_rows, gaia_source_id_to_healpix
from hou_compact.gaia import sha256_file

USER_AGENT = "HOU-COMPACT/0.1 (public astronomy research; selective acquisition)"
_ALLOWED_PREFIX = "https://data.desi.lbl.gov/"


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return Table.read(path).to_pandas()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("gaia", type=Path, help="Gaia seed table containing source_id")
    parser.add_argument("probe", type=Path, help="DESI probe CSV with exists=true rows")
    parser.add_argument("--output", type=Path, default=Path("outputs/desi_epochs.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw/desi"))
    parser.add_argument("--max-files", type=int, default=20)
    parser.add_argument("--max-file-gb", type=float, default=1.0)
    parser.add_argument("--max-total-gb", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--remove-fits-after-extraction", action="store_true")
    return parser.parse_args()


def _as_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin({"1", "true", "yes"})


def _safe_relative_path(value: object) -> Path:
    path = Path(str(value))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path: {value!r}")
    return path


def download_file(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    timeout: float,
    retries: int,
) -> tuple[int, str]:
    """Atomically download one allow-listed file and return size and SHA256."""
    if not url.startswith(_ALLOWED_PREFIX):
        raise ValueError(f"URL outside DESI allow-list: {url}")
    if destination.exists():
        size = destination.stat().st_size
        if size > max_bytes:
            raise ValueError(f"cached file exceeds byte limit: {destination}")
        return size, sha256_file(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        temp_name: str | None = None
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response:
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > max_bytes:
                    raise ValueError(f"remote file exceeds byte limit: {length} > {max_bytes}")
                digest = hashlib.sha256()
                written = 0
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent,
                    prefix=f".{destination.name}.",
                    delete=False,
                ) as handle:
                    temp_name = handle.name
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError(
                                f"download exceeded byte limit: {written} > {max_bytes}"
                            )
                        handle.write(chunk)
                        digest.update(chunk)
                os.replace(temp_name, destination)
                return written, digest.hexdigest()
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            last_error = error
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)
            if isinstance(error, ValueError) or attempt == retries:
                raise
            time.sleep(1.0 * 2**attempt)
    assert last_error is not None
    raise last_error


def main() -> None:
    args = parse_args()
    if args.max_files < 1:
        raise ValueError("max_files must be positive")
    if args.max_file_gb <= 0 or args.max_total_gb <= 0:
        raise ValueError("byte limits must be positive")
    if args.retries < 0:
        raise ValueError("retries must be non-negative")

    gaia = read_table(args.gaia)
    if "source_id" not in gaia.columns:
        raise KeyError("Gaia table has no source_id column")
    probe = pd.read_csv(args.probe)
    required_probe = {"exists", "url", "relative_path", "survey", "program", "healpix"}
    missing = sorted(required_probe - set(probe.columns))
    if missing:
        raise KeyError(f"probe table is missing columns: {missing}")

    gaia = gaia.copy()
    gaia["healpix"] = [gaia_source_id_to_healpix(int(value)) for value in gaia["source_id"]]
    source_ids_by_pixel = {
        int(healpix): group["source_id"].astype("int64").tolist()
        for healpix, group in gaia.groupby("healpix")
    }

    existing = probe.loc[_as_bool(probe["exists"])].copy()
    existing = existing.sort_values(
        ["healpix", "survey", "program"], kind="stable"
    ).head(args.max_files)
    max_file_bytes = int(args.max_file_gb * 1024**3)
    max_total_bytes = int(args.max_total_gb * 1024**3)
    total_downloaded = 0
    extracted: list[pd.DataFrame] = []
    file_records: list[dict[str, object]] = []

    for _, item in existing.iterrows():
        healpix = int(item["healpix"])
        selected_ids = source_ids_by_pixel.get(healpix, [])
        if not selected_ids:
            continue
        destination = args.cache_dir / _safe_relative_path(item["relative_path"])
        remaining = max_total_bytes - total_downloaded
        if remaining <= 0:
            break
        allowed = min(max_file_bytes, remaining)
        size, digest = download_file(
            str(item["url"]),
            destination,
            max_bytes=allowed,
            timeout=args.timeout,
            retries=args.retries,
        )
        total_downloaded += size
        rows = extract_single_epoch_rows(destination, selected_ids)
        rows["survey"] = str(item["survey"])
        rows["program"] = str(item["program"])
        rows["source_url"] = str(item["url"])
        rows["source_file_sha256"] = digest
        extracted.append(rows)
        file_records.append(
            {
                "url": str(item["url"]),
                "relative_path": str(item["relative_path"]),
                "local_path": str(destination),
                "sha256": digest,
                "size_bytes": size,
                "seed_source_count_in_pixel": len(selected_ids),
                "extracted_epoch_rows": len(rows),
            }
        )
        if args.remove_fits_after_extraction:
            destination.unlink(missing_ok=True)

    if extracted:
        epochs = pd.concat(extracted, ignore_index=True)
        key = ["source_id", "targetid", "expid", "survey", "program"]
        epochs = epochs.drop_duplicates(key).sort_values(
            ["source_id", "mjd", "expid"], kind="stable"
        )
    else:
        epochs = pd.DataFrame()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    epochs.to_csv(args.output, index=False)
    manifest = {
        "gaia_input": str(args.gaia),
        "gaia_input_sha256": sha256_file(args.gaia),
        "probe_input": str(args.probe),
        "probe_input_sha256": sha256_file(args.probe),
        "output": str(args.output),
        "output_sha256": sha256_file(args.output),
        "existing_probe_rows_considered": len(existing),
        "files_acquired": len(file_records),
        "downloaded_or_reused_bytes": total_downloaded,
        "extracted_epoch_rows": len(epochs),
        "unique_gaia_sources_with_epochs": (
            int(epochs["source_id"].nunique()) if not epochs.empty else 0
        ),
        "limits": {
            "max_files": args.max_files,
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
        },
        "files": file_records,
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
