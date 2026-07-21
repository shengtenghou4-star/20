# Gaia v6 and covariance CI audit

Created: 2026-07-22

This audit covers the exact current main branch after:

- correcting GSP-Phot radius fields to come from `gaiadr3.astrophysical_parameters`;
- validating SB1/SB1C `bit_index` values;
- decoding fixed-length sparse Gaia `corr_vec` arrays with DPAC-compatible non-zero compaction;
- rejecting ambiguous vector layouts;
- correcting the ambiguity test fixture;
- preserving Gaia TAP success/failure receipts and the full WP0-WP5 synthetic suite.

Passing CI validates software and query plumbing. The controlled live v6 receipt separately establishes whether the public Gaia and DESI stages executed.
