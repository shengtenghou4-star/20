# WP5 spectral multiplicity CI audit

Created: 2026-07-22

This audit covers the exact current main branch after adding a conservative one-template versus two-shift spectral comparison:

- relativistic wavelength shifts;
- non-negative line-depth amplitudes;
- weighted one- and two-component fits;
- BIC penalty for the additional velocity and amplitude;
- minimum velocity-separation and secondary-amplitude gates;
- synthetic single-lined, double-lined, weak-secondary, and invalid-input controls;
- all prior Gaia, DESI, covariance, visit, mass, contamination, triage, and privacy tests.

Passing CI validates the numerical software contract only. Production use still requires a stellar template library, real DESI spectra, control samples, and sensitivity audits.
