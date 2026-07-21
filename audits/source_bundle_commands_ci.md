# Private source-bundle command CI audit

Created: 2026-07-22

This marker triggers diagnosable CI against the exact current HOU-COMPACT main branch after adding:

- source-level spectral NPZ ingestion and hashed output manifests;
- source-level SED NPZ ingestion and hashed output manifests;
- explicit source/solution keys for downstream duplicate-safe evidence assembly;
- preserved fit settings, array shapes, template labels, and band names;
- private-data and interpretation boundaries;
- the complete hierarchy, stripped-star, independent-primary, novelty, evidence-assembly, and claim-readiness contract;
- all prior HOU-COMPACT tests.

Passing CI validates software syntax, lint, and synthetic behavior. Real spectra, photometry, templates, extinction, calibration, and source-level conclusions remain private scientific inputs.
