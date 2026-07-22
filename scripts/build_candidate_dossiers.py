#!/usr/bin/env python3
"""Generate private, blinded Markdown dossiers from a HOU-COMPACT triage table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.candidate_dossier import (
    DossierConfig,
    build_candidate_dossier,
    stable_blind_identifier,
)
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
    parser.add_argument("triage", type=Path, help="candidate-sensitive triage table")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/private_candidate_dossiers"),
    )
    parser.add_argument(
        "--blind-key-file",
        type=Path,
        help="private key material used only for stable HMAC dossier identifiers",
    )
    parser.add_argument("--minimum-triage-rank", type=int, default=3)
    parser.add_argument("--maximum-dossiers", type=int, default=100)
    parser.add_argument(
        "--include-source-identifiers",
        action="store_true",
        help="private-vault mode; writes Gaia identifiers into dossier Markdown",
    )
    parser.add_argument(
        "--acknowledge-private-output",
        action="store_true",
        help="required because dossier files are candidate-sensitive",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.acknowledge_private_output:
        raise ValueError("--acknowledge-private-output is required")
    if args.minimum_triage_rank < 0:
        raise ValueError("minimum_triage_rank must be non-negative")
    if args.maximum_dossiers < 1:
        raise ValueError("maximum_dossiers must be positive")
    if not args.include_source_identifiers and args.blind_key_file is None:
        raise ValueError(
            "--blind-key-file is required unless --include-source-identifiers is explicit"
        )

    triage = read_table(args.triage)
    required = {"source_id", "solution_id", "triage_rank", "triage_stage"}
    missing = sorted(required - set(triage.columns))
    if missing:
        raise KeyError(f"triage table is missing columns: {missing}")
    if triage.duplicated(["source_id", "solution_id"]).any():
        raise ValueError("triage table contains duplicate source/solution rows")

    selected = triage.loc[
        pd.to_numeric(triage["triage_rank"], errors="coerce").ge(
            args.minimum_triage_rank
        )
    ].copy()
    sort_columns = ["triage_rank"]
    ascending = [False]
    if "minimum_m2_q16_solar" in selected.columns:
        sort_columns.append("minimum_m2_q16_solar")
        ascending.append(False)
    selected = selected.sort_values(
        sort_columns,
        ascending=ascending,
        kind="stable",
        na_position="last",
    ).head(args.maximum_dossiers)

    secret_key: bytes | None = None
    blind_key_sha256: str | None = None
    if args.blind_key_file is not None:
        secret_key = args.blind_key_file.read_bytes()
        if len(secret_key) < 16:
            raise ValueError("blind key file must contain at least 16 bytes")
        blind_key_sha256 = sha256_file(args.blind_key_file)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    index_records: list[dict[str, object]] = []
    for _, row in selected.iterrows():
        if args.include_source_identifiers:
            dossier_id = f"HC-PRIVATE-{int(row['source_id'])}-{int(row['solution_id'])}"
        else:
            assert secret_key is not None
            dossier_id = stable_blind_identifier(
                row["source_id"],
                row["solution_id"],
                secret_key,
            )
        path = args.output_dir / f"{dossier_id}.md"
        content = build_candidate_dossier(
            row.to_dict(),
            dossier_id=dossier_id,
            config=DossierConfig(
                include_source_identifiers=args.include_source_identifiers
            ),
        )
        path.write_text(content, encoding="utf-8")
        index_records.append(
            {
                "dossier_id": dossier_id,
                "path": str(path),
                "sha256": sha256_file(path),
                "triage_stage": row["triage_stage"],
                "triage_rank": row["triage_rank"],
                "source_identifiers_in_markdown": args.include_source_identifiers,
            }
        )

    index = pd.DataFrame.from_records(index_records)
    index_path = args.output_dir / "INDEX.csv"
    index.to_csv(index_path, index=False)
    manifest = {
        "triage_input": str(args.triage),
        "triage_input_sha256": sha256_file(args.triage),
        "output_dir": str(args.output_dir),
        "index": str(index_path),
        "index_sha256": sha256_file(index_path),
        "input_rows": len(triage),
        "eligible_rows": len(selected),
        "dossiers_written": len(index),
        "minimum_triage_rank": args.minimum_triage_rank,
        "maximum_dossiers": args.maximum_dossiers,
        "source_identifiers_in_markdown": args.include_source_identifiers,
        "blind_key_sha256": blind_key_sha256,
        "claim_boundary": (
            "Dossiers are candidate-sensitive follow-up records, not compact-object "
            "classifications. Store all generated files in the private encrypted vault."
        ),
    }
    manifest_path = args.output_dir / "MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
