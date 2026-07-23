#!/usr/bin/env python3
"""Split the private Dark-668 seed into deterministic resumable shards.

Rows are assigned round-robin by frozen ``priority_rank`` so every shard receives
roughly equal target counts and a mix of priorities. The source-level shard remains
private; the public summary contains counts only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from hou_compact.gaia import sha256_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("seed", type=Path)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/private/dark668_shard_seed.csv"),
    )
    parser.add_argument(
        "--safe-summary",
        type=Path,
        default=Path("outputs/dark668_shard_seed_summary.json"),
    )
    return parser.parse_args()


def slice_seed(
    seed: pd.DataFrame,
    *,
    shard_index: int,
    shard_count: int,
) -> pd.DataFrame:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must lie in [0, shard_count)")
    required = {"source_id", "priority_rank"}
    missing = sorted(required - set(seed.columns))
    if missing:
        raise KeyError(f"seed is missing columns: {missing}")
    ranks = pd.to_numeric(seed["priority_rank"], errors="raise").astype("int64")
    if ranks.duplicated().any() or (ranks < 1).any():
        raise ValueError("priority_rank must contain unique positive integers")
    source_ids = seed["source_id"].astype("string")
    if source_ids.isna().any() or source_ids.duplicated().any():
        raise ValueError("source_id must be present and unique")
    mask = ((ranks - 1) % shard_count).eq(shard_index)
    output = seed.loc[mask].copy()
    output["priority_rank"] = ranks.loc[mask]
    output["source_id"] = source_ids.loc[mask]
    return output.sort_values("priority_rank", kind="stable").reset_index(drop=True)


def candidate_safe_shard_summary(
    full_seed: pd.DataFrame,
    shard: pd.DataFrame,
    *,
    shard_index: int,
    shard_count: int,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "shard_index": shard_index,
        "shard_count": shard_count,
        "full_seed_rows": int(len(full_seed)),
        "shard_rows": int(len(shard)),
        "assignment": "(priority_rank - 1) modulo shard_count",
        "source_level_output_written": True,
        "public_commit_policy": (
            "Never commit or upload the plaintext shard seed or its identifiers."
        ),
    }
    if "population" in shard.columns:
        payload["population_counts"] = {
            str(key): int(value)
            for key, value in shard["population"].value_counts().sort_index().items()
        }
    return payload


def main() -> None:
    args = parse_args()
    seed = pd.read_csv(args.seed, dtype={"source_id": "string"})
    shard = slice_seed(
        seed,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shard.to_csv(args.output, index=False)
    payload = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "seed_input_sha256": sha256_file(args.seed),
        "summary": candidate_safe_shard_summary(
            seed,
            shard,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
        ),
        "source_level_output_path": str(args.output),
    }
    args.safe_summary.parent.mkdir(parents=True, exist_ok=True)
    args.safe_summary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
