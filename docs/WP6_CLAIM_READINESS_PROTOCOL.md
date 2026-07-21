# WP6 — Claim-readiness protocol

Frozen: 2026-07-22

## Purpose

The final gate separates a promising follow-up target from an evidence package that is ready for serious claim review. Its strongest output is `claim_audit_ready_not_classified`; no software status is a compact-object classification.

## Required upstream evidence

A row must first have:

- follow-up triage rank at least 4 with no unresolved upstream blockers;
- an independently scored Gaia-orbit versus DESI-visit product;
- a Gaia-correlation-aware companion-mass product;
- a completed Gaia-side blend and contamination audit.

## Luminous-companion rejection

Two independent checks are required:

1. a one-template versus two-velocity spectral comparison;
2. a one-template versus two-template broad-band SED comparison.

Strong two-component evidence stops the compact-companion claim path and records `luminous_companion_evidence_present`. Weak evidence remains unresolved and cannot be silently treated as a clean result.

## Alternative astrophysical explanations

The evidence package must explicitly record outcomes for:

- hierarchical multiple systems;
- stripped-star or unusual luminous-star models;
- an independently derived primary-star mass;
- catalogue and literature novelty.

A missing audit is a blocker. A prior compact-object claim is recorded as non-novel and must be reconciled before any discovery language.

## Allowed terminal states

- `upstream_evidence_incomplete`: orbit, mass, or triage gates are not satisfied;
- `luminous_companion_evidence_present`: strong spectral or SED multiplicity evidence exists;
- `claim_audit_incomplete`: a final rejection, primary-mass, hierarchy, stripped-star, or novelty check is missing or unresolved;
- `claim_audit_ready_not_classified`: every required audit field is present and accepted under the frozen policy.

The output field `claim_authorized` is always false. Human scientific review, source-level inspection, uncertainty sensitivity tests, and external replication remain mandatory.

## Reproducible command

```bash
python scripts/assess_claim_readiness.py \
  outputs/merged_claim_evidence.csv \
  --output outputs/claim_readiness.csv
```

The command writes a compact result table and a manifest containing input/output hashes, row counts, status counts, and the interpretation boundary.
