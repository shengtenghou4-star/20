#!/usr/bin/env python3
"""Build private, pseudonymized follow-up cards from merged HOU-COMPACT evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd
from astropy.table import Table

from hou_compact.candidate_cards import (
    CandidateCardConfig,
    build_candidate_card,
    candidate_card_eligibility,
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
    parser.add_argument("evidence", type=Path, help="merged triage and WP5 evidence table")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/private_candidate_cards"),
    )
    parser.add_argument("--minimum-triage-rank", type=int, default=4)
    parser.add_argument("--salt-env", default="HOU_COMPACT_CARD_SALT")
    parser.add_argument(
        "--include-source-id",
        action="store_true",
        help="only use in a protected private output location",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    salt = os.environ.get(args.salt_env, "")
    if not salt:
        raise RuntimeError(
            f"missing non-empty pseudonym salt in environment variable {args.salt_env}"
        )
    evidence = read_table(args.evidence)
    required = {"source_id", "solution_id"}
    missing = sorted(required - set(evidence.columns))
    if missing:
        raise KeyError(f"evidence table is missing columns: {missing}")
    if evidence.duplicated(["source_id", "solution_id"]).any():
        raise ValueError("evidence table contains duplicate source/solution rows")

    config = CandidateCardConfig(
        minimum_triage_rank=args.minimum_triage_rank,
        include_source_id=args.include_source_id,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index_records: list[dict[str, object]] = []
    rejected_records: list[dict[str, object]] = []

    for row in evidence.to_dict(orient="records"):
        eligible, reasons = candidate_card_eligibility(row, config)
        if not eligible:
            rejected_records.append(
                {
                    "source_id": row.get("source_id")
                    if args.include_source_id
                    else None,
                    "solution_id": row.get("solution_id"),
                    "reasons": ";".join(reasons),
                }
            )
            continue
        card = build_candidate_card(row, salt=salt, config=config)
        candidate_id = str(card["identity"]["candidate_id"])
        card_path = args.output_dir / f"{candidate_id}.json"
        card_path.write_text(
            json.dumps(card, indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        index_records.append(
            {
                "candidate_id": candidate_id,
                "solution_id": row.get("solution_id"),
                "triage_stage": row.get("triage_stage"),
                "triage_rank": row.get("triage_rank"),
                "minimum_m2_q16_solar": row.get("minimum_m2_q16_solar"),
                "gaia_contamination_status": row.get(
                    "gaia_contamination_status"
                ),
                "card_path": str(card_path),
                "card_sha256": sha256_file(card_path),
            }
        )

    index = pd.DataFrame(index_records)
    rejected = pd.DataFrame(rejected_records)
    index_path = args.output_dir / "index.csv"
    rejected_path = args.output_dir / "rejected.csv"
    index.to_csv(index_path, index=False)
    rejected.to_csv(rejected_path, index=False)
    manifest = {
        "evidence_input": str(args.evidence),
        "evidence_input_sha256": sha256_file(args.evidence),
        "output_dir": str(args.output_dir),
        "eligible_cards": len(index),
        "rejected_rows": len(rejected),
        "index_sha256": sha256_file(index_path),
        "rejected_sha256": sha256_file(rejected_path),
        "settings": {
            "minimum_triage_rank": args.minimum_triage_rank,
            "include_source_id": args.include_source_id,
            "salt_environment_variable": args.salt_env,
        },
        "privacy_boundary": (
            "Candidate cards are generated under outputs/ and are ignored by Git. "
            "Public reports should use pseudonyms only."
        ),
        "claim_boundary": (
            "Cards are private follow-up targets, not compact-object classifications."
        ),
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
