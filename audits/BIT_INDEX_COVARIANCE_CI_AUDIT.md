# Gaia bit-index and sparse-covariance CI audit

Created: 2026-07-22

This audit covers the exact current main branch after aligning Gaia DR3 NSS covariance handling with the official data model and public DPAC `nsstools` behavior:

- `SB1` requires `bit_index=127`; `SB1C` requires `bit_index=31`;
- fixed-length sparse `corr_vec` arrays are compacted from finite non-zero elements in original order;
- compact and explicit leading-block serializations are supported only when unambiguous;
- ambiguous layouts and mismatched bit indices fail closed;
- raw vector length, coefficient count, decoding mode, and covariance repair are recorded;
- correlated mass inference and all prior WP0-WP5 tests remain in scope.

Passing CI validates the synthetic software contract. Live Gaia rows must still undergo serialization and reference-parity audits before mass rankings are trusted.
