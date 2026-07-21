"""Auditable alternative-hypothesis aggregation for HOU-COMPACT WP5/WP6.

The module summarizes caller-supplied checks for hierarchical multiples and stripped-star
interpretations. It does not perform image, spectral, or stellar-evolution modelling. A
hypothesis can be disfavored only when every frozen mandatory check is present.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


_ALLOWED_OUTCOMES = {"supports", "disfavors", "neutral", "not_done"}


@dataclass(frozen=True)
class AlternativeHypothesisConfig:
    """Frozen mandatory checks for the two principal luminous alternatives."""

    hierarchy_required_checks: tuple[str, ...] = (
        "high_resolution_imaging",
        "long_baseline_rv_trend",
        "astrometric_acceleration",
        "third_light_or_composite_sed",
    )
    stripped_star_required_checks: tuple[str, ...] = (
        "uv_excess",
        "helium_or_abundance_spectrum",
        "hot_component_sed",
        "stellar_evolution_consistency",
    )

    def __post_init__(self) -> None:
        for name, checks in (
            ("hierarchy_required_checks", self.hierarchy_required_checks),
            ("stripped_star_required_checks", self.stripped_star_required_checks),
        ):
            if not checks or any(not str(check).strip() for check in checks):
                raise ValueError(f"{name} must contain non-empty check names")
            normalized = [
                str(check).strip().casefold().replace("-", "_").replace(" ", "_")
                for check in checks
            ]
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{name} contains duplicate check names")


def _normalize_hypothesis(value: object) -> str:
    text = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "hierarchy": "hierarchy",
        "hierarchical_multiple": "hierarchy",
        "hierarchical_triple": "hierarchy",
        "triple": "hierarchy",
        "stripped_star": "stripped_star",
        "stripped": "stripped_star",
    }
    if text not in aliases:
        raise ValueError(f"unsupported alternative hypothesis: {value!r}")
    return aliases[text]


def _normalize_check(value: object) -> str:
    text = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    if not text:
        raise ValueError("check_name must be non-empty")
    return text


def _normalize_outcome(value: object) -> str:
    text = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    if text not in _ALLOWED_OUTCOMES:
        raise ValueError(f"unsupported check outcome: {value!r}")
    return text


def _summarize_one(
    hypothesis: str,
    records: list[dict[str, str]],
    required_checks: tuple[str, ...],
) -> dict[str, object]:
    required = {_normalize_check(check) for check in required_checks}
    by_check: dict[str, dict[str, str]] = {}
    for record in records:
        check = record["check_name"]
        if check in by_check:
            raise ValueError(f"duplicate {hypothesis} check: {check}")
        by_check[check] = record

    missing = sorted(
        check
        for check in required
        if check not in by_check or by_check[check]["outcome"] == "not_done"
    )
    supporting = sorted(
        check for check, record in by_check.items() if record["outcome"] == "supports"
    )
    disfavoring = sorted(
        check for check, record in by_check.items() if record["outcome"] == "disfavors"
    )
    neutral = sorted(
        check for check, record in by_check.items() if record["outcome"] == "neutral"
    )

    prefix = "hierarchy" if hypothesis == "hierarchy" else "stripped_star"
    if supporting:
        status = f"{prefix}_supported"
    elif missing:
        status = f"{prefix}_audit_incomplete"
    elif required.issubset(set(disfavoring)):
        status = f"{prefix}_disfavored"
    else:
        status = f"no_{prefix}_support"

    references = sorted(
        {
            record["reference"]
            for record in records
            if record["reference"]
        }
    )
    return {
        f"{prefix}_audit_status": status,
        f"{prefix}_required_checks": ";".join(sorted(required)),
        f"{prefix}_completed_check_count": len(required) - len(missing),
        f"{prefix}_missing_checks": ";".join(missing),
        f"{prefix}_supporting_checks": ";".join(supporting),
        f"{prefix}_disfavoring_checks": ";".join(disfavoring),
        f"{prefix}_neutral_checks": ";".join(neutral),
        f"{prefix}_references": ";".join(references),
    }


def audit_alternative_hypotheses(
    checks: Iterable[Mapping[str, object]],
    config: AlternativeHypothesisConfig = AlternativeHypothesisConfig(),
) -> dict[str, object]:
    """Summarize mandatory hierarchy and stripped-star checks for one source."""

    grouped: dict[str, list[dict[str, str]]] = {
        "hierarchy": [],
        "stripped_star": [],
    }
    for raw in checks:
        hypothesis = _normalize_hypothesis(raw.get("hypothesis"))
        grouped[hypothesis].append(
            {
                "check_name": _normalize_check(raw.get("check_name")),
                "outcome": _normalize_outcome(raw.get("outcome")),
                "reference": str(raw.get("reference", "")).strip(),
                "notes": str(raw.get("notes", "")).strip(),
            }
        )

    hierarchy = _summarize_one(
        "hierarchy",
        grouped["hierarchy"],
        config.hierarchy_required_checks,
    )
    stripped = _summarize_one(
        "stripped_star",
        grouped["stripped_star"],
        config.stripped_star_required_checks,
    )
    return {
        **hierarchy,
        **stripped,
        "alternative_hypothesis_interpretation_boundary": (
            "Statuses summarize supplied mandatory checks. They do not prove a dark "
            "companion, and unmodelled alternatives may remain."
        ),
    }
