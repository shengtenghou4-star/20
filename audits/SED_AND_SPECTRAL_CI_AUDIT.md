# WP5 spectral and SED multiplicity CI audit

Created: 2026-07-22

This audit covers the exact current main branch after adding two independent luminous-companion checks:

- one shifted template versus a two-velocity spectral mixture with BIC penalties;
- one scaled SED template versus a two-template non-negative mixture;
- conservative secondary-amplitude and secondary-flux-fraction gates;
- synthetic single, composite, weak-secondary, and invalid-input controls;
- all existing Gaia, DESI, covariance, independent-visit, mass, contamination, triage, and privacy tests.

Passing CI validates the numerical software contract only. Production use requires real DESI spectra, a documented stellar template library, calibrated photometry, extinction/parallax treatment, and known control samples.
