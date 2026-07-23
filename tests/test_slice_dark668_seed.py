from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "slice_dark668_seed.py"
_SPEC = importlib.util.spec_from_file_location("slice_dark668_seed", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

slice_seed = _MODULE.slice_seed
candidate_safe_shard_summary = _MODULE.candidate_safe_shard_summary


def _seed(rows: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": [str(1_000_000_000_000_000_000 + index) for index in range(rows)],
            "priority_rank": list(range(1, rows + 1)),
            "population": ["RGB" if index % 2 == 0 else "MS" for index in range(rows)],
        }
    )


def test_round_robin_shards_cover_seed_exactly_once() -> None:
    seed = _seed(17)
    shards = [slice_seed(seed, shard_index=index, shard_count=4) for index in range(4)]
    combined = pd.concat(shards, ignore_index=True)
    assert sorted(combined["source_id"].tolist()) == sorted(seed["source_id"].tolist())
    assert combined["source_id"].is_unique
    assert [len(shard) for shard in shards] == [5, 4, 4, 4]
    assert shards[0]["priority_rank"].tolist() == [1, 5, 9, 13, 17]


def test_shard_assignment_is_deterministic_under_input_reordering() -> None:
    seed = _seed(12)
    shuffled = seed.sample(frac=1.0, random_state=42).reset_index(drop=True)
    first = slice_seed(seed, shard_index=2, shard_count=5)
    second = slice_seed(shuffled, shard_index=2, shard_count=5)
    pd.testing.assert_frame_equal(first, second)


def test_invalid_shard_configuration_fails_closed() -> None:
    seed = _seed()
    with pytest.raises(ValueError, match="shard_count"):
        slice_seed(seed, shard_index=0, shard_count=0)
    with pytest.raises(ValueError, match="shard_index"):
        slice_seed(seed, shard_index=4, shard_count=4)


def test_duplicate_priority_rank_is_rejected() -> None:
    seed = _seed()
    seed.loc[1, "priority_rank"] = 1
    with pytest.raises(ValueError, match="priority_rank"):
        slice_seed(seed, shard_index=0, shard_count=2)


def test_safe_summary_contains_counts_not_identifiers() -> None:
    seed = _seed(11)
    shard = slice_seed(seed, shard_index=1, shard_count=3)
    summary = candidate_safe_shard_summary(
        seed,
        shard,
        shard_index=1,
        shard_count=3,
    )
    serialized = str(summary)
    assert summary["full_seed_rows"] == 11
    assert summary["shard_rows"] == len(shard)
    assert "1000000000000000000" not in serialized
