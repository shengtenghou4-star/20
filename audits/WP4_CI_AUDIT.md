# WP4 CI audit trigger

Created: 2026-07-22

This branch exists to run the repository's pull-request CI against the complete WP0-WP4 implementation currently on `main`.

Audit scope:

- import and syntax validation;
- Ruff static checks across `src`, `tests`, and `scripts`;
- deterministic unit tests for mass functions, inclination-aware roots, Gaia HEALPix decoding, DESI FITS row alignment, Keplerian orbit evaluation, GSP-Phot primary-mass proxies, Monte Carlo mass products, and follow-up gates.

No scientific result is certified by CI. Passing CI only establishes that the tested implementation behaves as specified on synthetic fixtures.
