"""Candidate-safe population summaries for sequential HOU-COMPACT evidence gates.

This module deliberately emits aggregate counts only. It never returns source IDs,
TARGETIDs, candidate ranks, or row-level measurements.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

HOLD_STAGE_ORDER: tuple[str, ...] = (
    "gaia_quality_hold",
    "desi_orbit_hold",
    "mass_inference_hold",
    "contamination_resolution_hold",
    "roche_geometry_hold",
)
FOLLOWUP_STAGES: tuple[str, ...] = (
    "orbit_supported_lower_mass",
    "high_minimum_mass_followup",
    "very_high_minimum_mass_followup",
)
ALLOWED_STAGES = frozenset((*HOLD_STAGE_ORDER, *FOLLOWUP_STAGES))


@dataclass(frozen=True)
class AttritionRow:
    """One sequential evidence-gate population count."""

    order: int
    stage: str
    entered: int
    held: int
    advanced: int
    held_fraction_of_entered: float
    advanced_fraction_of_cohort: float

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def _require_columns(frame: pd.DataFrame, required: Iterable[str]) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise KeyError(f"triage table is missing columns: {missing}")


def _normalized_stage_series(frame: pd.DataFrame) -> pd.Series:
    _require_columns(frame, ("triage_stage",))
    stages = frame["triage_stage"].astype("string").str.strip()
    if stages.isna().any() or stages.eq("").any():
        raise ValueError("triage_stage contains missing or empty values")
    unknown = sorted(set(stages) - ALLOWED_STAGES)
    if unknown:
        raise ValueError(f"unknown triage stages: {unknown}")
    return stages


def sequential_attrition(frame: pd.DataFrame) -> pd.DataFrame:
    """Return stage-by-stage entered, held, and advanced counts.

    Each row in a triage table is assigned to its first sequential blocking stage or a
    final follow-up stage. Therefore a hold stage's ``entered`` count is the cohort size
    minus all earlier holds, and ``advanced`` is the population reaching the next gate.
    """
    stages = _normalized_stage_series(frame)
    total = int(len(stages))
    counts = stages.value_counts().to_dict()
    entered = total
    rows: list[AttritionRow] = []
    for order, stage in enumerate(HOLD_STAGE_ORDER, start=1):
        held = int(counts.get(stage, 0))
        if held > entered:
            raise ValueError(f"stage {stage} holds more rows than entered")
        advanced = entered - held
        rows.append(
            AttritionRow(
                order=order,
                stage=stage,
                entered=entered,
                held=held,
                advanced=advanced,
                held_fraction_of_entered=(held / entered if entered else 0.0),
                advanced_fraction_of_cohort=(advanced / total if total else 0.0),
            )
        )
        entered = advanced

    final_count = int(sum(int(counts.get(stage, 0)) for stage in FOLLOWUP_STAGES))
    if final_count != entered:
        raise ValueError(
            "final follow-up counts do not equal the population advancing past all holds"
        )
    rows.append(
        AttritionRow(
            order=len(HOLD_STAGE_ORDER) + 1,
            stage="all_evidence_gates_passed",
            entered=entered,
            held=0,
            advanced=entered,
            held_fraction_of_entered=0.0,
            advanced_fraction_of_cohort=(entered / total if total else 0.0),
        )
    )
    return pd.DataFrame.from_records([row.to_record() for row in rows])


def stage_counts(frame: pd.DataFrame) -> dict[str, int]:
    """Return all frozen stages in stable order, including zero-count stages."""
    stages = _normalized_stage_series(frame)
    counts = stages.value_counts().to_dict()
    return {
        stage: int(counts.get(stage, 0))
        for stage in (*HOLD_STAGE_ORDER, *FOLLOWUP_STAGES)
    }


def _token_counts(series: pd.Series) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for value in series.fillna("").astype(str):
        for token in value.split(";"):
            normalized = token.strip()
            if normalized:
                counter[normalized] += 1
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def blocker_counts(frame: pd.DataFrame) -> dict[str, int]:
    """Count every semicolon-delimited blocking reason without row identifiers."""
    _require_columns(frame, ("blockers",))
    return _token_counts(frame["blockers"])


def caution_counts(frame: pd.DataFrame) -> dict[str, int]:
    """Count every semicolon-delimited caution reason without row identifiers."""
    _require_columns(frame, ("cautions",))
    return _token_counts(frame["cautions"])


def clean_epoch_distribution(frame: pd.DataFrame) -> dict[str, int]:
    """Return candidate-safe counts for 0, 1, 2, and 3+ clean DESI epochs."""
    _require_columns(frame, ("n_clean_epochs",))
    values = pd.to_numeric(frame["n_clean_epochs"], errors="coerce")
    missing = int(values.isna().sum())
    finite = values.dropna()
    if (finite < 0).any():
        raise ValueError("n_clean_epochs contains negative values")
    return {
        "missing": missing,
        "0": int(finite.eq(0).sum()),
        "1": int(finite.eq(1).sum()),
        "2": int(finite.eq(2).sum()),
        "3_plus": int(finite.ge(3).sum()),
    }


def minimum_mass_threshold_counts(
    frame: pd.DataFrame,
    thresholds: tuple[float, ...] = (1.4, 3.0, 5.0, 8.0),
) -> dict[str, dict[str, int]]:
    """Count finite q16 minimum masses above frozen descriptive thresholds.

    Counts are reported for all finite mass products and separately for rows passing all
    evidence gates. They are follow-up strata, not object classifications.
    """
    _require_columns(frame, ("minimum_m2_q16_solar", "triage_stage"))
    if not thresholds or any(not np.isfinite(value) or value <= 0 for value in thresholds):
        raise ValueError("thresholds must be finite and positive")
    if tuple(sorted(set(thresholds))) != thresholds:
        raise ValueError("thresholds must be strictly increasing and unique")

    stages = _normalized_stage_series(frame)
    masses = pd.to_numeric(frame["minimum_m2_q16_solar"], errors="coerce")
    finite = np.isfinite(masses)
    passed = stages.isin(FOLLOWUP_STAGES)
    output: dict[str, dict[str, int]] = {}
    for threshold in thresholds:
        key = f"q16_ge_{threshold:g}_solar"
        above = finite & masses.ge(threshold)
        output[key] = {
            "all_finite_mass_rows": int(above.sum()),
            "all_evidence_gates_passed": int((above & passed).sum()),
        }
    return output


def candidate_safe_attrition_summary(frame: pd.DataFrame) -> dict[str, object]:
    """Build the aggregate manuscript-facing HOU-COMPACT attrition payload."""
    flow = sequential_attrition(frame)
    stages = stage_counts(frame)
    return {
        "schema_version": "0.1",
        "candidate_safe": True,
        "cohort_rows": int(len(frame)),
        "stage_counts": stages,
        "sequential_flow": flow.to_dict(orient="records"),
        "blocker_counts": blocker_counts(frame),
        "caution_counts": caution_counts(frame),
        "clean_epoch_distribution": clean_epoch_distribution(frame),
        "minimum_mass_threshold_counts": minimum_mass_threshold_counts(frame),
        "all_evidence_gates_passed": int(sum(stages[stage] for stage in FOLLOWUP_STAGES)),
        "interpretation_boundary": (
            "These are aggregate evidence-stage and follow-up counts. They contain no "
            "source identifiers and do not classify any object as a compact companion."
        ),
    }
