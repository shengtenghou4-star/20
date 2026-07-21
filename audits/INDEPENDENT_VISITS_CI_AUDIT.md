# Independent-visit CI audit

Created: 2026-07-22

This audit covers the exact current main branch after the WP3 anti-pseudoreplication amendment:

- nearby DESI exposures are grouped into independent visits;
- visit RV and MJD are inverse-variance weighted;
- within-visit disagreement inflates uncertainty;
- scientific gates count visits instead of raw spectra;
- Gaia v5, correlation-aware WP4, WP5 contamination, triage, and private-card tests remain in scope.

Passing CI validates the synthetic software contract only. Live Gaia/DESI execution and astronomical interpretation remain separate gates.
