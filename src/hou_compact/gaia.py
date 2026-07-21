"""Gaia TAP acquisition with immutable query and result manifests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pyvo

DEFAULT_GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_sync_query(
    query_path: Path,
    output_path: Path,
    *,
    tap_url: str = DEFAULT_GAIA_TAP_URL,
    overwrite: bool = False,
) -> dict[str, object]:
    """Execute a frozen ADQL query and write a result plus JSON manifest.

    The output format is inferred by Astropy from the file extension. ECSV is the
    recommended pilot format because it is self-describing and diff-friendly for small
    tables. Large production tables should use FITS or Parquet through a later staged
    conversion.
    """
    query_path = query_path.resolve()
    output_path = output_path.resolve()

    if not query_path.is_file():
        raise FileNotFoundError(query_path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {output_path}")

    query = query_path.read_text(encoding="utf-8")
    if not query.strip():
        raise ValueError("ADQL query is empty")

    service = pyvo.dal.TAPService(tap_url)
    result = service.search(query)
    table = result.to_table()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    table.write(output_path, overwrite=overwrite)

    manifest: dict[str, object] = {
        "created_utc": datetime.now(UTC).isoformat(),
        "tap_url": tap_url,
        "query_path": str(query_path),
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "row_count": len(table),
        "column_names": list(table.colnames),
    }
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest
