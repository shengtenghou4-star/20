# WP5 — Contaminant-rejection protocol

Frozen: 2026-07-22

## Purpose

WP5 asks whether an orbit-supported, high-minimum-mass SB1/SB1C system can still be explained by ordinary luminous or structured alternatives. The default answer remains “unresolved” until each required check is completed.

## Gaia-side evidence

The v5 pilot preserves diagnostics for:

- duplicated source processing;
- IPD multi-peak windows;
- odd/truncated windows associated with nearby detections;
- scan-angle-dependent IPD goodness of fit;
- astrometric excess-noise significance;
- BP/RP blended and contaminated transit fractions;
- deblended RVS transit fraction;
- published photometric variability;
- availability of XP, RVS, and epoch products.

These indicators reveal possible structure, blending, or processing difficulty. They are caution evidence, not automatic vetoes. A clean Gaia-side record also cannot exclude an unresolved luminous companion.

## Mandatory follow-up checks

Every priority system must receive:

1. direct image inspection in Gaia and independent surveys;
2. a composite-spectrum and double-lined-spectrum search;
3. single-star versus composite SED fitting;
4. known binary, variable, compact-candidate, and literature crossmatches;
5. hierarchical triple and stripped-star alternative modelling;
6. independent primary-star characterization;
7. novelty and prior-publication audit.

Where available, Gaia XP and mean RVS spectra should be retrieved. DESI spectra and atmospheric parameters should be assessed independently of the Gaia GSP-Phot proxy.

## Status language

Permitted intermediate statuses include:

- `contamination_signals_present`;
- `no_signal_in_available_fields_but_incomplete`;
- `no_gaia_side_signal_detected`;
- `luminous_secondary_test_pending`;
- `hierarchy_test_pending`;
- `novelty_audit_pending`.

“No Gaia-side signal detected” is not equivalent to “dark companion confirmed.” Compact-object language remains prohibited until the complete evidence package survives independent review.

## Advancement gate

A system can enter a private candidate-card queue only after:

- WP3 independent orbit support;
- WP4 correlation-aware minimum-mass inference;
- Gaia-side contamination audit;
- explicit record of every pending external check;
- no unresolved fatal catalogue or crossmatch conflict;
- provenance hashes for every input and derived table.

Candidate cards remain private until catalogue precedence and literature novelty have been audited.
