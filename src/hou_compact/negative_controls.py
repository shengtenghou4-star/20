"""Deterministic negative controls for Gaia–DESI fixed-orbit validation.

The controls test chance phase alignment and the fitted additive velocity-offset
contract. Public products are aggregate-only; source-level scores remain private.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from hou_compact.validation import score_orbit_consistency


@dataclass(frozen=True)
class OrbitScoreThresholds:
    """Frozen descriptive thresholds used by control summaries."""

    delta_chi2: tuple[float, ...] = (4.0, 9.0, 16.0)
    maximum_reduced_chi2: float = 5.0
    minimum_phase_coverage: float = 0.20
    minimum_clean_visits: int = 3

    def __post_init__(self) -> None:
        invalid_delta = any(
            not math.isfinite(value) or value < 0 for value in self.delta_chi2
        )
        if not self.delta_chi2 or invalid_delta:
            raise ValueError("delta_chi2 thresholds must be finite and non-negative")
        if tuple(sorted(set(self.delta_chi2))) != self.delta_chi2:
            raise ValueError("delta_chi2 thresholds must be strictly increasing")
        if (
            not math.isfinite(self.maximum_reduced_chi2)
            or self.maximum_reduced_chi2 <= 0
        ):
            raise ValueError("maximum_reduced_chi2 must be finite and positive")
        if not 0 <= self.minimum_phase_coverage <= 1:
            raise ValueError("minimum_phase_coverage must lie in [0, 1]")
        if self.minimum_clean_visits < 2:
            raise ValueError("minimum_clean_visits must be at least 2")


def deterministic_control_seed(
    source_id: int,
    solution_id: int,
    repetition: int,
    base_seed: int,
    label: str,
) -> int:
    """Return a stable 64-bit seed without exposing identifiers in output names."""
    if repetition < 0:
        raise ValueError("repetition must be non-negative")
    payload = f"{base_seed}|{source_id}|{solution_id}|{repetition}|{label}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def phase_scramble_gaia_rows(
    gaia_rows: pd.DataFrame,
    *,
    repetition: int,
    base_seed: int = 20260722,
) -> pd.DataFrame:
    """Shift every orbit by an independent deterministic random phase."""
    required = {"source_id", "solution_id", "period", "t_periastron"}
    missing = sorted(required - set(gaia_rows.columns))
    if missing:
        raise KeyError(f"gaia_rows is missing columns: {missing}")
    result = gaia_rows.copy()
    shifted: list[float] = []
    for row in result.itertuples(index=False):
        source_id = int(getattr(row, "source_id"))
        solution_id = int(getattr(row, "solution_id"))
        period = float(getattr(row, "period"))
        t_periastron = float(getattr(row, "t_periastron"))
        if not math.isfinite(period) or period <= 0:
            raise ValueError("period values must be finite and positive")
        if not math.isfinite(t_periastron):
            raise ValueError("t_periastron values must be finite")
        seed = deterministic_control_seed(
            source_id,
            solution_id,
            repetition,
            base_seed,
            "phase_scramble",
        )
        phase = float(np.random.default_rng(seed).uniform(0.0, 1.0))
        shifted.append(t_periastron + phase * period)
    result["t_periastron"] = shifted
    return result


def add_deterministic_source_offsets(
    epoch_rows: pd.DataFrame,
    *,
    base_seed: int = 20260722,
    offset_sigma_kms: float = 50.0,
) -> pd.DataFrame:
    """Add one deterministic velocity offset per source for invariance testing."""
    required = {"source_id", "vrad"}
    missing = sorted(required - set(epoch_rows.columns))
    if missing:
        raise KeyError(f"epoch_rows is missing columns: {missing}")
    if not math.isfinite(offset_sigma_kms) or offset_sigma_kms <= 0:
        raise ValueError("offset_sigma_kms must be finite and positive")
    result = epoch_rows.copy()
    offsets: dict[int, float] = {}
    for raw_source_id in result["source_id"].unique():
        source_id = int(raw_source_id)
        seed = deterministic_control_seed(
            source_id,
            0,
            0,
            base_seed,
            "systemic_offset",
        )
        offsets[source_id] = float(
            np.random.default_rng(seed).normal(0.0, offset_sigma_kms)
        )
    velocities = pd.to_numeric(result["vrad"], errors="raise")
    result["vrad"] = velocities + result["source_id"].map(offsets)
    return result


def _eligible_scored_mask(
    scores: pd.DataFrame,
    thresholds: OrbitScoreThresholds,
) -> pd.Series:
    required = {
        "status",
        "n_clean_epochs",
        "phase_coverage",
        "orbit_reduced_chi2",
        "delta_chi2_constant_minus_orbit",
    }
    missing = sorted(required - set(scores.columns))
    if missing:
        raise KeyError(f"score table is missing columns: {missing}")
    visits = pd.to_numeric(scores["n_clean_epochs"], errors="coerce")
    coverage = pd.to_numeric(scores["phase_coverage"], errors="coerce")
    reduced_chi2 = pd.to_numeric(
        scores["orbit_reduced_chi2"], errors="coerce"
    )
    return (
        scores["status"].eq("scored")
        & visits.ge(thresholds.minimum_clean_visits)
        & coverage.ge(thresholds.minimum_phase_coverage)
        & reduced_chi2.le(thresholds.maximum_reduced_chi2)
    )


def aggregate_orbit_score_counts(
    scores: pd.DataFrame,
    thresholds: OrbitScoreThresholds = OrbitScoreThresholds(),
) -> dict[str, object]:
    """Return aggregate counts at frozen orbit-support thresholds."""
    eligible = _eligible_scored_mask(scores, thresholds)
    delta = pd.to_numeric(
        scores["delta_chi2_constant_minus_orbit"], errors="coerce"
    )
    return {
        "score_rows": int(len(scores)),
        "scored_rows": int(scores["status"].eq("scored").sum()),
        "eligible_absolute_fit_rows": int(eligible.sum()),
        "delta_chi2_counts": {
            f"ge_{value:g}": int((eligible & delta.ge(value)).sum())
            for value in thresholds.delta_chi2
        },
    }


def run_phase_scramble_control(
    gaia_rows: pd.DataFrame,
    epoch_rows: pd.DataFrame,
    *,
    repetitions: int = 100,
    base_seed: int = 20260722,
    thresholds: OrbitScoreThresholds = OrbitScoreThresholds(),
    scorer_kwargs: dict[str, object] | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Run the observed score and an aggregate phase-scrambled null ensemble."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    kwargs = dict(scorer_kwargs or {})
    kwargs.setdefault("min_clean_epochs", 2)
    observed_scores = score_orbit_consistency(gaia_rows, epoch_rows, **kwargs)
    observed = aggregate_orbit_score_counts(observed_scores, thresholds)

    records: list[dict[str, object]] = []
    for repetition in range(repetitions):
        scrambled = phase_scramble_gaia_rows(
            gaia_rows,
            repetition=repetition,
            base_seed=base_seed,
        )
        scores = score_orbit_consistency(scrambled, epoch_rows, **kwargs)
        aggregate = aggregate_orbit_score_counts(scores, thresholds)
        record: dict[str, object] = {
            "repetition": repetition,
            "scored_rows": aggregate["scored_rows"],
            "eligible_absolute_fit_rows": aggregate["eligible_absolute_fit_rows"],
        }
        counts = aggregate["delta_chi2_counts"]
        assert isinstance(counts, dict)
        for key, value in counts.items():
            record[f"delta_chi2_{key}"] = int(value)
        records.append(record)
    null = pd.DataFrame.from_records(records)

    empirical: dict[str, float] = {}
    observed_counts = observed["delta_chi2_counts"]
    assert isinstance(observed_counts, dict)
    for key, observed_count in observed_counts.items():
        column = f"delta_chi2_{key}"
        exceedances = int(null[column].ge(int(observed_count)).sum())
        empirical[key] = (1.0 + exceedances) / (1.0 + repetitions)

    ranges = {
        column: {
            "minimum": int(null[column].min()),
            "median": float(null[column].median()),
            "maximum": int(null[column].max()),
        }
        for column in null.columns
        if column.startswith("delta_chi2_")
    }
    summary = {
        "schema_version": "0.1",
        "candidate_safe": True,
        "repetitions": repetitions,
        "base_seed": base_seed,
        "thresholds": asdict(thresholds),
        "observed": observed,
        "null_count_ranges": ranges,
        "empirical_tail_probabilities": empirical,
        "interpretation_boundary": (
            "The phase-scramble control tests chance phase alignment at fixed cadence "
            "and orbit amplitude. It is not a compact-object test."
        ),
    }
    return null, summary


def audit_systemic_offset_invariance(
    gaia_rows: pd.DataFrame,
    epoch_rows: pd.DataFrame,
    *,
    base_seed: int = 20260722,
    tolerance: float = 1e-8,
    scorer_kwargs: dict[str, object] | None = None,
) -> dict[str, object]:
    """Verify that per-source additive RV offsets do not alter fit statistics."""
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    kwargs = dict(scorer_kwargs or {})
    kwargs.setdefault("min_clean_epochs", 2)
    baseline = score_orbit_consistency(gaia_rows, epoch_rows, **kwargs)
    shifted_epochs = add_deterministic_source_offsets(
        epoch_rows,
        base_seed=base_seed,
    )
    shifted = score_orbit_consistency(gaia_rows, shifted_epochs, **kwargs)
    merged = baseline.merge(
        shifted,
        on=["source_id", "solution_id"],
        suffixes=("_baseline", "_shifted"),
        validate="one_to_one",
    )
    comparable = merged["status_baseline"].eq("scored") & merged[
        "status_shifted"
    ].eq("scored")
    fields = (
        "constant_chi2",
        "orbit_chi2",
        "delta_chi2_constant_minus_orbit",
        "orbit_reduced_chi2",
    )
    maximum_differences: dict[str, float] = {}
    failures = 0
    for field in fields:
        baseline_values = pd.to_numeric(
            merged.loc[comparable, f"{field}_baseline"], errors="coerce"
        )
        shifted_values = pd.to_numeric(
            merged.loc[comparable, f"{field}_shifted"], errors="coerce"
        )
        difference = (baseline_values - shifted_values).abs()
        maximum = float(difference.max()) if not difference.empty else 0.0
        maximum_differences[field] = maximum
        failures += int(difference.gt(tolerance).sum())
    return {
        "schema_version": "0.1",
        "candidate_safe": True,
        "comparable_scored_rows": int(comparable.sum()),
        "tolerance": tolerance,
        "maximum_absolute_differences": maximum_differences,
        "values_above_tolerance": failures,
        "status": "pass" if failures == 0 else "failure",
        "interpretation_boundary": (
            "This audit verifies the additive systemic-velocity nuisance model; it "
            "does not test source identity or compact-object status."
        ),
    }
