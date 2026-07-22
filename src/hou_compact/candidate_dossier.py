"""Deterministic, claim-bounded evidence dossiers for HOU-COMPACT follow-up targets.

Real dossiers are candidate-sensitive and belong in the encrypted/private evidence vault.
This module never assigns a compact-object class. It renders the current evidence gates,
missing tests, and blockers so that a visually impressive mass estimate cannot outrun the
independent orbit, contamination, novelty, and luminous-secondary checks.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class DossierConfig:
    """Rendering controls that keep source identity and claims explicit."""

    include_source_identifiers: bool = False
    title_prefix: str = "HOU-COMPACT follow-up dossier"


def stable_blind_identifier(
    source_id: object,
    solution_id: object,
    secret_key: bytes,
    *,
    length: int = 16,
) -> str:
    """Return a stable HMAC identifier without exposing a Gaia source identifier."""
    if not isinstance(secret_key, bytes) or len(secret_key) < 16:
        raise ValueError("secret_key must contain at least 16 bytes")
    if not isinstance(length, int) or not 10 <= length <= 32:
        raise ValueError("length must be an integer in [10, 32]")
    payload = f"{source_id}|{solution_id}".encode("utf-8")
    digest = hmac.new(secret_key, payload, hashlib.sha256).hexdigest()[:length]
    return f"HC-{digest.upper()}"


def _text(row: Mapping[str, object], key: str, default: str = "not available") -> str:
    value = row.get(key)
    if value is None:
        return default
    rendered = str(value).strip()
    if not rendered or rendered.lower() in {"nan", "none", "null"}:
        return default
    return rendered


def _number(row: Mapping[str, object], key: str) -> float | None:
    try:
        value = float(row.get(key))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _integer(row: Mapping[str, object], key: str) -> int | None:
    value = _number(row, key)
    return int(value) if value is not None and value.is_integer() else None


def _fmt(value: float | None, digits: int = 3, suffix: str = "") -> str:
    return "not available" if value is None else f"{value:.{digits}f}{suffix}"


def _status_mark(passed: bool | None) -> str:
    if passed is True:
        return "PASS"
    if passed is False:
        return "HOLD"
    return "PENDING"


def evidence_gate_summary(row: Mapping[str, object]) -> list[dict[str, object]]:
    """Return explicit gate states without inferring an astrophysical class."""
    orbit_status = _text(row, "orbit_status", _text(row, "status", ""))
    clean_epochs = _integer(row, "n_clean_epochs")
    phase_coverage = _number(row, "phase_coverage")
    delta_chi2 = _number(row, "delta_chi2_constant_minus_orbit")
    orbit_reduced_chi2 = _number(row, "orbit_reduced_chi2")
    orbit_ready = (
        orbit_status == "scored"
        and clean_epochs is not None
        and clean_epochs >= 3
        and phase_coverage is not None
        and phase_coverage >= 0.20
        and delta_chi2 is not None
        and delta_chi2 >= 9.0
        and orbit_reduced_chi2 is not None
        and orbit_reduced_chi2 <= 5.0
    )

    primary_status = _text(row, "primary_status", "")
    primary_width = _number(row, "fractional_68_width")
    primary_ready = (
        primary_status in {"scored", "weak_prior"}
        and primary_width is not None
        and primary_width <= 0.75
    )

    mass_status = _text(row, "mass_status", "")
    minimum_q16 = _number(row, "minimum_m2_q16_solar")
    mass_ready = mass_status == "scored" and minimum_q16 is not None

    high_risk = _integer(row, "gaia_contamination_high_risk_count")
    contamination_ready: bool | None
    if high_risk is None:
        contamination_ready = None
    else:
        contamination_ready = high_risk == 0

    spectral_status = _text(row, "spectral_evidence_status", "")
    spectral_ready: bool | None
    if not spectral_status:
        spectral_ready = None
    else:
        spectral_ready = spectral_status == "no_two_component_preference"

    sed_status = _text(row, "sed_evidence_status", "")
    sed_ready: bool | None
    if not sed_status:
        sed_ready = None
    else:
        sed_ready = sed_status == "no_composite_sed_preference"

    novelty_status = _text(row, "novelty_status", "")
    novelty_ready: bool | None
    if not novelty_status:
        novelty_ready = None
    else:
        novelty_ready = novelty_status in {"no_reference_match", "novelty_review_passed"}

    hierarchy_status = _text(row, "hierarchy_rejection_status", "")
    hierarchy_ready: bool | None
    if not hierarchy_status:
        hierarchy_ready = None
    else:
        hierarchy_ready = hierarchy_status == "alternatives_not_preferred"

    return [
        {"gate": "Independent DESI orbit support", "passed": orbit_ready},
        {"gate": "Primary-star mass constrained", "passed": primary_ready},
        {"gate": "Companion minimum-mass posterior", "passed": mass_ready},
        {"gate": "Gaia high-risk contamination cleared", "passed": contamination_ready},
        {"gate": "Double-lined spectral test", "passed": spectral_ready},
        {"gate": "Composite SED test", "passed": sed_ready},
        {"gate": "Known-system / novelty audit", "passed": novelty_ready},
        {"gate": "Triple / stripped-star alternatives", "passed": hierarchy_ready},
    ]


def build_candidate_dossier(
    row: Mapping[str, object],
    *,
    dossier_id: str,
    config: DossierConfig = DossierConfig(),
    generated_utc: str | None = None,
) -> str:
    """Render one Markdown dossier for a private follow-up target."""
    if not dossier_id or any(character in dossier_id for character in "/\\\n\r"):
        raise ValueError("dossier_id must be a safe non-empty identifier")
    generated = generated_utc or datetime.now(UTC).isoformat()
    gates = evidence_gate_summary(row)
    pass_count = sum(item["passed"] is True for item in gates)
    hold_count = sum(item["passed"] is False for item in gates)
    pending_count = sum(item["passed"] is None for item in gates)

    identity_lines = [f"- Dossier ID: `{dossier_id}`"]
    if config.include_source_identifiers:
        identity_lines.extend(
            [
                f"- Gaia DR3 source ID: `{_text(row, 'source_id')}`",
                f"- Gaia NSS solution ID: `{_text(row, 'solution_id')}`",
            ]
        )
    else:
        identity_lines.append("- Source identifiers: redacted by default")

    gate_lines = [
        f"- **{_status_mark(item['passed'])}** — {item['gate']}" for item in gates
    ]
    blockers = _text(row, "blockers", "none recorded")
    cautions = _text(row, "cautions", "none recorded")

    lines = [
        f"# {config.title_prefix}: {dossier_id}",
        "",
        "> **Claim boundary:** This is a follow-up evidence dossier, not a black-hole, "
        "neutron-star, white-dwarf, or compact-object classification. A high mass estimate "
        "cannot substitute for independent orbit support and contaminant rejection.",
        "",
        "## Identity and provenance",
        *identity_lines,
        f"- Generated UTC: `{generated}`",
        f"- Triage stage: `{_text(row, 'triage_stage')}`",
        f"- Triage rank: `{_text(row, 'triage_rank')}`",
        "",
        "## Evidence-gate scoreboard",
        f"- Passed: **{pass_count}**",
        f"- Held: **{hold_count}**",
        f"- Pending: **{pending_count}**",
        *gate_lines,
        "",
        "## Gaia orbital evidence",
        f"- NSS solution type: `{_text(row, 'nss_solution_type')}`",
        f"- Gaia significance: {_fmt(_number(row, 'significance'))}",
        f"- Spectroscopic-period confidence: {_fmt(_number(row, 'conf_spectro_period'))}",
        f"- Good Gaia primary RV observations: {_text(row, 'rv_n_good_obs_primary')}",
        f"- Period: {_fmt(_number(row, 'period'), 6, ' d')}",
        f"- Primary semi-amplitude: {_fmt(_number(row, 'semi_amplitude_primary'), 3, ' km/s')}",
        f"- Eccentricity: {_fmt(_number(row, 'eccentricity'))}",
        f"- Gaia flag bits set: `{_text(row, 'gaia_set_flag_bits', 'none recorded')}`",
        "",
        "## Independent DESI validation",
        f"- Orbit status: `{_text(row, 'orbit_status', _text(row, 'status'))}`",
        f"- Clean independent visits/epochs: {_text(row, 'n_clean_epochs')}",
        f"- Baseline: {_fmt(_number(row, 'baseline_days'), 3, ' d')}",
        f"- Phase coverage: {_fmt(_number(row, 'phase_coverage'))}",
        f"- Constant minus fixed-orbit delta chi-square: {_fmt(_number(row, 'delta_chi2_constant_minus_orbit'))}",
        f"- Fixed-orbit reduced chi-square: {_fmt(_number(row, 'orbit_reduced_chi2'))}",
        f"- Maximum pairwise RV significance: {_fmt(_number(row, 'max_pairwise_rv_significance'), 3, ' sigma')}",
        "",
        "## Mass evidence",
        f"- Primary prior status/method: `{_text(row, 'primary_status')}` / `{_text(row, 'method')}`",
        f"- Primary mass median: {_fmt(_number(row, 'primary_mass_solar'), 3, ' Msun')}",
        f"- Primary fractional 68% width: {_fmt(_number(row, 'fractional_68_width'))}",
        f"- Companion mass status: `{_text(row, 'mass_status')}`",
        f"- Edge-on minimum M2 q16/q50: {_fmt(_number(row, 'minimum_m2_q16_solar'), 3, ' Msun')} / {_fmt(_number(row, 'minimum_m2_q50_solar'), 3, ' Msun')}",
        f"- Isotropic M2 q16/q50: {_fmt(_number(row, 'isotropic_m2_q16_solar'), 3, ' Msun')} / {_fmt(_number(row, 'isotropic_m2_q50_solar'), 3, ' Msun')}",
        "",
        "## Contamination and luminous-secondary evidence",
        f"- Gaia contamination status: `{_text(row, 'gaia_contamination_status')}`",
        f"- High-risk / caution / context counts: {_text(row, 'gaia_contamination_high_risk_count')} / {_text(row, 'gaia_contamination_caution_count')} / {_text(row, 'gaia_contamination_context_count')}",
        f"- High-risk signals: `{_text(row, 'gaia_contamination_high_risk_signals', 'none recorded')}`",
        f"- Spectral multiplicity status: `{_text(row, 'spectral_evidence_status')}`",
        f"- Composite SED status: `{_text(row, 'sed_evidence_status')}`",
        f"- Hierarchy/stripped-star status: `{_text(row, 'hierarchy_rejection_status')}`",
        "",
        "## Novelty and external-catalogue audit",
        f"- Novelty status: `{_text(row, 'novelty_status')}`",
        f"- Closest known-system catalogue: `{_text(row, 'catalog_name')}`",
        f"- Catalogue match status: `{_text(row, 'match_status')}`",
        f"- Match separation: {_fmt(_number(row, 'match_separation_arcsec'), 4, ' arcsec')}",
        "",
        "## Current blockers and cautions",
        f"- Blockers: `{blockers}`",
        f"- Cautions: `{cautions}`",
        "",
        "## Mandatory next checks",
        "- Validate the primary-star model independently of Gaia single-star assumptions.",
        "- Inspect images and spectra for blending, line multiplicity, and luminous companions.",
        "- Compare against hierarchical-triple and stripped-star alternatives.",
        "- Complete known-system and literature novelty checks.",
        "- Seek additional spectroscopy or follow-up observations before any physical-class claim.",
        "",
    ]
    return "\n".join(lines)
