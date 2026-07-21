# DPAC nsstools parity CI audit

Created: 2026-07-22

This audit covers the exact current main branch after adding an independent Gaia covariance reference gate:

- optional `nsstools==0.1.12` reference dependency;
- live-row comparison of HOU-COMPACT correlation matrices with DPAC `nsstools.make_covmat`;
- strict parameter-order equality checks;
- candidate-safe aggregate parity receipts;
- corrected Gaia v6 `astrophysical_parameters` join;
- all prior WP0-WP5 synthetic tests and independent-visit safeguards.

Passing CI validates the software adapter. The controlled live workflow must still return Gaia rows and pass the reference comparison before correlated mass rankings are trusted.
