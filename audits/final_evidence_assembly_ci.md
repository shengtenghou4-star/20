# Final evidence assembly CI audit

Created: 2026-07-22

This marker triggers diagnosable CI against the exact current HOU-COMPACT main branch after adding:

- one-to-one source/solution merge validation;
- duplicate-row rejection;
- ambiguous non-key column collision rejection;
- per-table evidence-presence flags and coverage counts;
- automatic final claim-readiness evaluation on the merged table;
- a reproducible named-table command with complete input hashes;
- the invariant that missing evidence remains a blocker and `claim_authorized` remains false;
- all prior Gaia, DESI, covariance, independent-visit, mass, contamination, spectral, SED, novelty, triage, privacy, and claim-readiness tests.

Passing CI validates software behavior only. It does not validate any real candidate or authorize a classification.
