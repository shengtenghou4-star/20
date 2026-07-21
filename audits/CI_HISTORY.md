# CI audit history

Updated: 2026-07-22

- Early WP4/WP5 audit runs exposed one real numerical defect: unrestricted Newton iteration could diverge for a high-eccentricity Kepler equation test.
- The solver was replaced by a monotonic bracketed method and the boundary convention at positive pi was preserved.
- Post-fix audit PR #8 completed successfully.
- Later audits added preserved pytest/JUnit artifacts, Gaia covariance propagation, WP5 contamination checks, candidate-card serialization hardening, and independent DESI visit construction.
- PR #10 completed successfully: installation, Ruff lint, the full synthetic test suite, and diagnostic-artifact upload all passed for the independent-visit code snapshot.
- Superseded marker-only PRs #3, #4, #7, #8, and #9 were closed without merge; their success/failure records remain available as audit history.

CI validates synthetic software behavior. Live Gaia/DESI execution, catalogue serialization, and astrophysical claims remain separate gates.
