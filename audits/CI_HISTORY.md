# CI audit history

Updated: 2026-07-22

- Early WP4/WP5 audit runs exposed one real numerical defect: unrestricted Newton iteration could diverge for a high-eccentricity Kepler equation test.
- The solver was replaced by a monotonic bracketed method and the boundary convention at positive pi was preserved.
- Post-fix audit PR #8 completed successfully.
- Later audits added preserved pytest/JUnit artifacts, Gaia covariance propagation, WP5 contamination checks, candidate-card serialization hardening, and independent DESI visit construction.
- PR #10 is the active code audit for the independent-visit amendment. Older audit PRs are historical and may be closed without merging their marker-only commits.

CI validates synthetic software behavior. Live Gaia/DESI execution, catalogue serialization, and astrophysical claims remain separate gates.
