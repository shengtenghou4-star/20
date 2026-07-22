"""Candidate-safe sensitivity sweeps for frozen HOU-COMPACT triage thresholds."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, replace

import pandas as pd

from hou_compact.attrition import FOLLOWUP_STAGES, stage_counts
from hou_compact.triage import TriageConfig, triage_followup


@dataclass(frozen=True)
class SensitivityGrid:
    """Pre-specified threshold values for aggregate robustness analysis."""

    min_clean_desi_epochs: tuple[int, ...] = (2, 3)
    min_phase_coverage: tuple[float, ...] = (0.10, 0.20, 0.30)
    min_delta_chi2: tuple[float, ...] = (4.0, 9.0, 16.0)
    max_primary_fractional_width: tuple[float, ...] = (0.50, 0.75, 1.00)

    def __post_init__(self) -> None:
        if not self.min_clean_desi_epochs or any(
            value < 2 for value in self.min_clean_desi_epochs
        ):
            raise ValueError("clean-epoch thresholds must all be at least 2")
        if not self.min_phase_coverage or any(
            not 0 <= value <= 1 for value in self.min_phase_coverage
        ):
            raise ValueError("phase-coverage thresholds must lie in [0, 1]")
        if not self.min_delta_chi2 or any(
            value < 0 for value in self.min_delta_chi2
        ):
            raise ValueError("delta-chi2 thresholds must be non-negative")
        if not self.max_primary_fractional_width or any(
            value <= 0 for value in self.max_primary_fractional_width
        ):
            raise ValueError("primary-width thresholds must be positive")
        for values, name in (
            (self.min_clean_desi_epochs, "min_clean_desi_epochs"),
            (self.min_phase_coverage, "min_phase_coverage"),
            (self.min_delta_chi2, "min_delta_chi2"),
            (self.max_primary_fractional_width, "max_primary_fractional_width"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{name} must be strictly increasing and unique")

    @property
    def size(self) -> int:
        return (
            len(self.min_clean_desi_epochs)
            * len(self.min_phase_coverage)
            * len(self.min_delta_chi2)
            * len(self.max_primary_fractional_width)
        )


def _config_identifier(config: TriageConfig) -> str:
    payload = {
        "min_clean_desi_epochs": config.min_clean_desi_epochs,
        "min_phase_coverage": config.min_phase_coverage,
        "min_delta_chi2": config.min_delta_chi2,
        "max_primary_fractional_68_width": config.max_primary_fractional_68_width,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def iter_sensitivity_configs(
    grid: SensitivityGrid = SensitivityGrid(),
    base_config: TriageConfig = TriageConfig(),
) -> list[TriageConfig]:
    """Materialize the deterministic Cartesian threshold grid."""
    return [
        replace(
            base_config,
            min_clean_desi_epochs=clean_epochs,
            min_phase_coverage=phase_coverage,
            min_delta_chi2=delta_chi2,
            max_primary_fractional_68_width=primary_width,
        )
        for clean_epochs, phase_coverage, delta_chi2, primary_width in itertools.product(
            grid.min_clean_desi_epochs,
            grid.min_phase_coverage,
            grid.min_delta_chi2,
            grid.max_primary_fractional_width,
        )
    ]


def _stratum_counts(
    frame: pd.DataFrame,
    stages: pd.Series,
    column: str,
) -> dict[str, dict[str, int]]:
    if column not in frame.columns:
        return {}
    values = (
        frame[column]
        .astype("string")
        .fillna("missing")
        .str.strip()
        .replace("", "missing")
    )
    passed = stages.isin(FOLLOWUP_STAGES)
    output: dict[str, dict[str, int]] = {}
    for value in sorted(values.unique()):
        mask = values.eq(value)
        output[str(value)] = {
            "cohort_rows": int(mask.sum()),
            "all_evidence_gates_passed": int((mask & passed).sum()),
        }
    return output


def run_triage_sensitivity(
    frame: pd.DataFrame,
    *,
    grid: SensitivityGrid = SensitivityGrid(),
    base_config: TriageConfig = TriageConfig(),
) -> pd.DataFrame:
    """Re-evaluate every row over the frozen grid and return aggregate-only results."""
    if frame.empty:
        raise ValueError("triage input must not be empty")
    normalized = frame.reset_index(drop=True)
    records = normalized.to_dict(orient="records")
    outputs: list[dict[str, object]] = []
    configs = iter_sensitivity_configs(grid, base_config)
    if len(configs) != grid.size:
        raise RuntimeError("sensitivity grid size mismatch")

    for config in configs:
        triage = pd.DataFrame([triage_followup(row, config) for row in records])
        stages = triage["triage_stage"].astype("string")
        counts = stage_counts(triage)
        passed = stages.isin(FOLLOWUP_STAGES)
        outputs.append(
            {
                "config_id": _config_identifier(config),
                "min_clean_desi_epochs": config.min_clean_desi_epochs,
                "min_phase_coverage": config.min_phase_coverage,
                "min_delta_chi2": config.min_delta_chi2,
                "max_primary_fractional_68_width": (
                    config.max_primary_fractional_68_width
                ),
                "cohort_rows": len(triage),
                "all_evidence_gates_passed": int(passed.sum()),
                "orbit_supported_lower_mass": counts["orbit_supported_lower_mass"],
                "high_minimum_mass_followup": counts["high_minimum_mass_followup"],
                "very_high_minimum_mass_followup": counts[
                    "very_high_minimum_mass_followup"
                ],
                "gaia_quality_hold": counts["gaia_quality_hold"],
                "desi_orbit_hold": counts["desi_orbit_hold"],
                "mass_inference_hold": counts["mass_inference_hold"],
                "contamination_resolution_hold": counts[
                    "contamination_resolution_hold"
                ],
                "roche_geometry_hold": counts["roche_geometry_hold"],
                "sb1_strata": _stratum_counts(
                    normalized,
                    stages,
                    "nss_solution_type",
                ),
                "identifier_path_strata": _stratum_counts(
                    normalized,
                    stages,
                    "source_match_mode",
                ),
            }
        )
    return pd.DataFrame.from_records(outputs).sort_values(
        [
            "min_clean_desi_epochs",
            "min_phase_coverage",
            "min_delta_chi2",
            "max_primary_fractional_68_width",
        ],
        kind="stable",
    ).reset_index(drop=True)


def candidate_safe_sensitivity_summary(results: pd.DataFrame) -> dict[str, object]:
    """Summarize the range of outcomes across a completed aggregate sensitivity grid."""
    required = {
        "config_id",
        "cohort_rows",
        "all_evidence_gates_passed",
        "high_minimum_mass_followup",
        "very_high_minimum_mass_followup",
    }
    missing = sorted(required - set(results.columns))
    if missing:
        raise KeyError(f"sensitivity results are missing columns: {missing}")
    if results.empty:
        raise ValueError("sensitivity results must not be empty")
    if results["config_id"].duplicated().any():
        raise ValueError("sensitivity results contain duplicate config IDs")
    if results["cohort_rows"].nunique() != 1:
        raise ValueError("cohort size changed across sensitivity configurations")

    def range_record(column: str) -> dict[str, int]:
        values = pd.to_numeric(results[column], errors="raise").astype("int64")
        return {"minimum": int(values.min()), "maximum": int(values.max())}

    return {
        "schema_version": "0.1",
        "candidate_safe": True,
        "configuration_count": int(len(results)),
        "cohort_rows": int(results.iloc[0]["cohort_rows"]),
        "all_evidence_gates_passed_range": range_record(
            "all_evidence_gates_passed"
        ),
        "high_minimum_mass_followup_range": range_record(
            "high_minimum_mass_followup"
        ),
        "very_high_minimum_mass_followup_range": range_record(
            "very_high_minimum_mass_followup"
        ),
        "grid_columns": [
            "min_clean_desi_epochs",
            "min_phase_coverage",
            "min_delta_chi2",
            "max_primary_fractional_68_width",
        ],
        "interpretation_boundary": (
            "Sensitivity ranges quantify threshold dependence of aggregate follow-up "
            "stages. They contain no source identifiers and do not classify compact objects."
        ),
    }
