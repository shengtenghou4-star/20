# Private-pilot support CI audit

Created: 2026-07-22

This audit covers the exact current public pipeline after adding:

- official Gaia bit-index and sparse `corr_vec` handling;
- independent DPAC `nsstools` covariance parity support;
- corrected Gaia v6 astrophysical-parameters join;
- Gaia TAP success/failure receipts;
- independent DESI visit construction;
- seed-density DESI acquisition prioritization;
- all existing WP0-WP5 tests.

The companion private repository runs candidate-sensitive acquisition and persists compact evidence. Passing this audit validates public software behavior only; real source-level evidence remains private and separately gated.
