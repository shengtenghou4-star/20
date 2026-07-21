# Catalogue and literature novelty CI audit

Created: 2026-07-22

This marker triggers diagnosable CI against the exact current HOU-COMPACT main branch after adding:

- explicit SIMBAD, VizieR, and ADS coverage requirements;
- conservative compact-object and known-binary precedence vocabularies;
- positional-separation rejection accounting;
- source-level identifiers and bibcode preservation;
- a reproducible match-table reduction command with hashed manifests;
- integration-compatible `novelty_audit_status` values for the final claim-readiness gate;
- all prior Gaia, DESI, covariance, independent-visit, mass, contamination, spectral, SED, triage, privacy, and claim-readiness tests.

Passing CI validates software behavior only. A clean precedence search does not prove astrophysical novelty or validate a compact companion.
