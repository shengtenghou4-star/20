# CI audit history

Updated: 2026-07-22

- Early WP4/WP5 audit runs exposed one real numerical defect: unrestricted Newton iteration could diverge for a high-eccentricity Kepler equation test.
- The solver was replaced by a monotonic bracketed method and the boundary convention at positive pi was preserved.
- Post-fix audit PR #8 completed successfully.
- Later audits added preserved pytest/JUnit artifacts, Gaia covariance propagation, WP5 contamination checks, candidate-card serialization hardening, and independent DESI visit construction.
- PR #10 completed successfully: installation, Ruff lint, the full synthetic test suite, and diagnostic-artifact upload all passed for the independent-visit code snapshot.
- PR #15 passed the public support code used by the bounded private Gaia-DESI pilot, including DPAC covariance-reference support and DESI seed-density prioritization.
- PR #16 passed the conservative one-template versus two-velocity spectral multiplicity module.
- PR #17 passed the combined spectral and composite-SED evidence modules.
- PR #18 passed the final claim-readiness state machine and its invariant that software never authorizes an astrophysical classification.
- PR #19 passed the explicit SIMBAD/VizieR/ADS novelty-coverage and precedence-reduction module.
- PR #20 exposed a dataframe-boundary defect: missing left-join evidence became the text-like value `nan`, producing a generic unaccepted-status blocker.
- The missing-value normalizer was repaired on main. PR #21 then passed the complete duplicate-safe final-evidence assembly audit with precise missing-audit blockers.
- PR #22 passed independent multi-method primary-mass consensus, tension diagnostics, and severe-conflict blocking.
- PR #23 exposed a normalized-name collision in the hierarchy/stripped-star mandatory-check configuration; PR #24 passed after equivalent spellings were normalized before duplicate validation.
- PR #25 passed private source-level spectral and SED NPZ ingestion, hashed manifests, and explicit source/solution evidence keys.
- Encrypted live relay run `29854769813` exposed a Gaia ADQL parser incompatibility in the repeated arithmetic `ORDER BY` expression. Query v7 now orders by the selected `pk1_cubed_proxy` alias.
- Encrypted live relay run `29855057052` established that v7 parses but the synchronous Gaia TAP endpoint aborts the joined and ordered query before completion.
- PR #26 passed the persistent asynchronous UWS acquisition path, including remote job provenance, terminal-phase failure receipts, timeouts, fetch retries, cleanup behavior, and synchronous compatibility.
- Superseded marker-only PRs are closed without merge; their success/failure records remain available as audit history.

CI validates synthetic software behavior. Live Gaia/DESI execution, source-level spectral/SED analysis, catalogue retrieval, and astrophysical claims remain separate gates.
