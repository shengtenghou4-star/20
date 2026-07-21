"""Catalogue and literature novelty evidence for HOU-COMPACT WP6.

The module consumes already-retrieved crossmatch records. It never treats absence from one
catalogue as proof of novelty: a clean status requires an explicit list of searched
catalogues and literature services. Records are reduced to identifiers, object types,
bibcodes, titles, and angular separations so the audit remains reproducible.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class NoveltyConfig:
    """Frozen conservative vocabulary and coverage policy."""

    required_services: tuple[str, ...] = ("SIMBAD", "VizieR", "ADS")
    maximum_match_separation_arcsec: float = 5.0
    compact_claim_patterns: tuple[str, ...] = (
        r"\bblack\s*hole\b",
        r"\bneutron\s*star\b",
        r"\bcompact\s*object\b",
        r"\bwhite\s*dwarf\b",
        r"\bBH\s*candidate\b",
        r"\bNS\s*candidate\b",
    )
    binary_patterns: tuple[str, ...] = (
        r"\bbinary\b",
        r"\bspectroscopic\s*binary\b",
        r"\beclipsing\b",
        r"\bSB1\b",
        r"\bSB2\b",
        r"\bmultiple\s*system\b",
    )

    def __post_init__(self) -> None:
        if not self.required_services:
            raise ValueError("required_services must not be empty")
        if any(not str(service).strip() for service in self.required_services):
            raise ValueError("required_services must contain non-empty names")
        if (
            not math.isfinite(self.maximum_match_separation_arcsec)
            or self.maximum_match_separation_arcsec <= 0
        ):
            raise ValueError("maximum_match_separation_arcsec must be positive")
        for pattern in (*self.compact_claim_patterns, *self.binary_patterns):
            re.compile(pattern, flags=re.IGNORECASE)


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _optional_float(record: Mapping[str, object], key: str) -> float | None:
    try:
        value = float(record.get(key))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _matches_any(text: str, patterns: Sequence[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def audit_novelty_records(
    records: Iterable[Mapping[str, object]],
    *,
    searched_services: Iterable[str],
    config: NoveltyConfig = NoveltyConfig(),
) -> dict[str, object]:
    """Reduce crossmatch/literature records to a conservative novelty status."""

    searched = {str(service).strip().casefold() for service in searched_services if str(service).strip()}
    required = {service.casefold() for service in config.required_services}
    missing_services = sorted(
        service
        for service in config.required_services
        if service.casefold() not in searched
    )

    accepted: list[dict[str, object]] = []
    rejected_large_separation = 0
    for record in records:
        separation = _optional_float(record, "separation_arcsec")
        if separation is not None and separation > config.maximum_match_separation_arcsec:
            rejected_large_separation += 1
            continue
        accepted.append(dict(record))

    compact_claims: list[dict[str, object]] = []
    known_binaries: list[dict[str, object]] = []
    for record in accepted:
        evidence_text = " | ".join(
            filter(
                None,
                (
                    _text(record, "object_type"),
                    _text(record, "title"),
                    _text(record, "classification"),
                    _text(record, "notes"),
                ),
            )
        )
        if _matches_any(evidence_text, config.compact_claim_patterns):
            compact_claims.append(record)
        elif _matches_any(evidence_text, config.binary_patterns):
            known_binaries.append(record)

    object_ids = sorted(
        {
            _text(record, "object_id")
            for record in accepted
            if _text(record, "object_id")
        }
    )
    bibcodes = sorted(
        {
            _text(record, "bibcode")
            for record in accepted
            if _text(record, "bibcode")
        }
    )
    services_with_matches = sorted(
        {
            _text(record, "service")
            for record in accepted
            if _text(record, "service")
        }
    )

    if missing_services:
        status = "novelty_audit_incomplete"
    elif compact_claims:
        status = "prior_compact_object_claim_found"
    elif known_binaries:
        status = "known_binary_without_compact_object_claim"
    else:
        status = "no_prior_compact_object_claim_found"

    return {
        "novelty_audit_status": status,
        "novelty_searched_services": ";".join(sorted(searched)),
        "novelty_missing_services": ";".join(missing_services),
        "novelty_match_count": len(accepted),
        "novelty_compact_claim_count": len(compact_claims),
        "novelty_known_binary_count": len(known_binaries),
        "novelty_rejected_large_separation_count": rejected_large_separation,
        "novelty_services_with_matches": ";".join(services_with_matches),
        "novelty_object_ids": ";".join(object_ids),
        "novelty_bibcodes": ";".join(bibcodes),
        "novelty_interpretation_boundary": (
            "Catalogue and literature search results constrain precedence; absence of a "
            "match does not prove astrophysical novelty or validate a compact companion."
        ),
    }
