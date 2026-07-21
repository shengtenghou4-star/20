# Hierarchy and stripped-star alternative CI audit

Created: 2026-07-22

This marker triggers diagnosable CI against the exact current HOU-COMPACT main branch after adding:

- frozen mandatory checklists for hierarchical multiples and stripped-star alternatives;
- explicit `supports`, `disfavors`, `neutral`, and `not_done` outcomes;
- supporting evidence precedence over incomplete checklists;
- strict prevention of disfavored status when a mandatory check is missing;
- duplicate-check rejection and reference preservation;
- a reproducible long-table command with hashed manifest output;
- status values directly consumed by the final claim-readiness gate;
- all prior Gaia, DESI, covariance, visit, mass, contamination, spectral, SED, novelty, primary-consensus, evidence-assembly, privacy, and claim-readiness tests.

Passing CI validates software behavior only. These checks do not exhaust all stellar or instrumental alternatives.
