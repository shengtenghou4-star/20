# Live-run receipt CI audit

Created: 2026-07-22

This audit covers the exact current main branch after:

- Gaia TAP success and failure manifests;
- candidate-safe public workflow receipts;
- independent DESI visit construction;
- all WP0-WP5 synthetic tests.

The receipt contains no source identifiers or candidate rows. It exposes only step outcomes, schema, counts, hashes, bounded failure text, and aggregate DESI overlap statistics.

Passing CI validates software behavior only. The live workflow receipt is the separate evidence for archive execution.
