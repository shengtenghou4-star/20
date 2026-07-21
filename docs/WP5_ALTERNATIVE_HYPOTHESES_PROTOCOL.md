# WP5 — Hierarchy and stripped-star alternative protocol

Frozen: 2026-07-22

## Purpose

A high inferred companion mass and a single-lined spectrum can still arise from a structured luminous system. This protocol prevents hierarchy or stripped-star alternatives from being dismissed by one clean diagnostic.

The executable module aggregates completed checks; it does not perform the underlying imaging, spectroscopy, SED fitting, or stellar-evolution modelling.

## Hierarchical-multiple checks

The default pilot requires:

- high-resolution or archival image inspection;
- a long-baseline radial-velocity trend audit;
- an astrometric-acceleration audit;
- third-light or composite-SED evidence.

Allowed outcomes for each check are `supports`, `disfavors`, `neutral`, and `not_done`.

Terminal hierarchy statuses are:

- `hierarchy_supported`: at least one retained check supports a hierarchy;
- `hierarchy_audit_incomplete`: at least one mandatory check is missing or not done and none supports the hypothesis;
- `hierarchy_disfavored`: every mandatory check explicitly disfavors a hierarchy;
- `no_hierarchy_support`: all mandatory checks are complete, none supports a hierarchy, and at least one remains neutral.

## Stripped-star checks

The default pilot requires:

- ultraviolet-excess assessment;
- helium or abundance-sensitive spectroscopy;
- a hot-component SED assessment;
- stellar-evolution consistency modelling.

Terminal stripped-star statuses mirror the hierarchy statuses:

- `stripped_star_supported`;
- `stripped_star_audit_incomplete`;
- `stripped_star_disfavored`;
- `no_stripped_star_support`.

## Conservative ordering

A supporting check takes precedence over an incomplete checklist. Missing checks can never produce a disfavored status. Duplicate check names are rejected so repeated measurements from one evidence family cannot masquerade as independent rejection.

## Reproducible command

```bash
python scripts/audit_alternative_hypotheses.py \
  private/alternative_hypothesis_checks.csv \
  --output private/alternative_hypothesis_audit.csv
```

The long input table must preserve `(source_id, solution_id)`, hypothesis, check name, outcome, and preferably a reference plus notes. The output manifest records the input hash, row counts, and status distributions.

These statuses constrain two important alternatives. They do not prove a dark companion and do not exhaust all possible stellar or instrumental explanations.
