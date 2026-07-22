# HOU-COMPACT I — frozen manuscript and analysis plan

Frozen: 2026-07-22  
Status: internal analysis protocol; no compact-object claims

## Working title

**Auditing the high-minimum-mass tail of Gaia DR3 single-lined orbital solutions with independent DESI DR1 spectroscopy**

## Central scientific question

How many apparently massive, unseen companions in the Gaia DR3 SB1-family orbital catalogue survive a sequence of reproducible quality, stellar-parameter, geometry, multiplicity, and independent radial-velocity tests?

The paper is designed to remain scientifically interpretable under all three possible DESI outcomes:

1. one or more Gaia orbits receive strong independent DESI support;
2. DESI measurements exist but mostly reject or fail to constrain the Gaia orbits;
3. the frozen Gaia cohort has little or no usable DESI single-exposure overlap.

A null overlap or null validation result is not treated as a failed experiment. It quantifies the external-validation coverage and selection function of the chosen public surveys.

## Frozen cohort

Primary cohort: the 5,000-row Gaia v9 SB1/SB1C/AstroSpectroSB1 query ranked by the frozen mass-function proxy and filtered by the published Gaia significance requirement.

The exact query text, Gaia TAP job provenance, result hash, schema, row count, and ordering are versioned. Any later expanded or alternative cohort must receive a distinct query version and cannot silently replace the primary cohort.

## Pre-specified evidence stages

### Stage A — Gaia orbital quality

Required fields and gates:

- Gaia orbital significance;
- spectroscopic-period confidence;
- minimum number of good Gaia RV observations;
- decoded fatal and caution solution flags;
- explicit SB1 versus circular SB1C parameter convention;
- covariance reconstruction validated against the independent reference adapter.

Output: quality-pass, caution, or hold. No mass interpretation occurs before this stage.

### Stage B — primary-star inference

Primary-mass priors are derived from the frozen hierarchy of Gaia stellar products. Every row records the input method, quantiles, uncertainty width, and failure reason.

Rows with missing stellar information remain `input_error`; they are not counted as astrophysical rejections.

### Stage C — correlated minimum-companion-mass posterior

The edge-on minimum companion mass is inferred with the published Gaia covariance structure and primary-mass uncertainty. The principal screening statistic is the lower 16th percentile, `minimum_m2_q16_solar`, rather than the median or maximum.

Pre-specified descriptive thresholds:

- q16 ≥ 1.4 solar masses;
- q16 ≥ 3 solar masses;
- q16 ≥ 5 solar masses;
- q16 ≥ 8 solar masses.

These thresholds define follow-up strata, not object classes.

### Stage D — Gaia-side contamination audit

The following are separated rather than collapsed into a single score:

- high-risk blend or multiplicity signals;
- caution-only signals;
- NSS contextual signals;
- no signal in the available fields, explicitly marked incomplete.

A missing audit or a high-risk signal blocks clean high-mass prioritization.

### Stage E — Roche-geometry consistency

The primary radius must fit inside the Eggleton primary Roche lobe at periastron under propagated orbit and mass uncertainties.

Statuses:

- detached geometry consistent;
- near or overflowing Roche lobe;
- geometry inconsistent;
- input error.

Geometry inconsistency challenges the adopted Gaia orbit and/or single-star stellar model. Geometry consistency is necessary but not sufficient for a dark-companion interpretation.

### Stage F — DESI source association

Two identifier-based paths are evaluated independently:

1. the official NOIRLab Data Lab Gaia DR3 ↔ DESI DR1 zpix convenience crossmatch, followed by exact DESI TARGETID equality;
2. the official Gaia DR3-to-DR2 neighbourhood bridge, followed by exact DESI `REF_CAT='G2'` and `REF_ID` equality.

Path agreement is recorded. Source-level disagreement is fatal. Epoch-propagated positional matching remains diagnostic and cannot silently replace identifier evidence.

### Stage G — independent DESI visits

Single exposures are restored with official exposure MJD and arm-level S/N fields, quality-filtered, and aggregated into independent visits. Multiple exposures from the same visit cannot be counted as independent orbital phases.

The paper reports the number of Gaia sources with:

- zero usable DESI epochs;
- one usable visit;
- two usable visits;
- three or more usable visits;
- sufficient phase coverage for a fixed-orbit test.

### Stage H — fixed Gaia-orbit validation

The DESI velocities are compared with:

1. a constant-velocity model with one fitted systemic velocity;
2. the fixed Gaia orbit shape with one fitted DESI systemic-velocity offset.

The first-pass orbit model does not re-fit period, phase, eccentricity, argument of periastron, or K1. The principal comparison is

`Delta chi-square = chi-square_constant - chi-square_fixed_Gaia_orbit`.

Both models have the same number of fitted velocity-offset parameters. Absolute orbit fit quality, phase coverage, epoch count, jitter sensitivity, and pairwise RV significance are reported alongside Delta chi-square.

### Stage I — luminous-companion and hierarchy rejection

For systems that survive the earlier stages, the following remain mandatory:

- one-template versus two-template spectral comparison;
- single-star versus composite SED comparison;
- resolved-neighbour and crowding review;
- hierarchical-triple alternatives;
- stripped-star or interacting-binary alternatives;
- literature and catalogue novelty search.

No source advances to a public compact-object claim while any of these gates are missing.

## Primary outcomes

### Outcome 1 — high-minimum-mass tail

Report the number and fraction of mass-scored systems above each q16 threshold before and after:

- Gaia quality gates;
- Gaia-side high-risk contamination removal;
- Roche-geometry consistency;
- independent DESI orbit support.

The denominator is always stated explicitly. Missing-input rows are shown separately.

### Outcome 2 — attrition matrix

Produce a stage-by-stage flow table showing how many systems are held by each evidence gate. A system may carry multiple cautions, but the first sequential blocking stage defines the principal attrition category.

### Outcome 3 — DESI validation coverage

Quantify:

- exact Data Lab crossmatch coverage;
- accepted DR3-to-DR2 bridge coverage;
- verified MWS RV-file availability;
- exact epoch extraction yield;
- independent-visit yield;
- phase-coverage yield.

This is a survey-selection result even when the final orbit-support count is zero.

### Outcome 4 — orbit agreement and disagreement

For every scorable system, report the fixed-orbit and constant-model statistics. Population summaries include the distribution of Delta chi-square, reduced chi-square, residual RMS, baseline, phase coverage, and cross-survey systemic-velocity offsets.

### Outcome 5 — follow-up pool

Publish only aggregate counts until source-level release is approved. Any released table distinguishes:

- orbit-supported lower-mass systems;
- high-minimum-mass follow-up systems;
- very-high-minimum-mass follow-up systems;
- contamination-resolution holds;
- Roche-geometry holds;
- insufficient-DESI holds.

These are follow-up stages, not compact-object classifications.

## Statistical robustness analyses

The following sensitivity analyses are pre-specified:

1. minimum DESI visit count: 2 versus 3;
2. minimum phase coverage: 0.10, 0.20, and 0.30;
3. Delta chi-square gate: 4, 9, and 16;
4. DESI RV jitter floors spanning the documented pilot range;
5. arm S/N and RV-uncertainty quality thresholds;
6. primary-mass prior width threshold;
7. Gaia contamination caution inclusion versus exclusion;
8. Roche filling thresholds and eccentricity treatment;
9. TARGETID-only, REF_ID-only, and agreeing-dual-path source associations;
10. SB1 and SB1C strata reported separately.

Every sensitivity run receives a manifest containing input hashes, settings, output hash, and UTC creation time.

## Negative controls and falsification tests

- shuffled DESI epoch times within suitable control strata;
- phase-scrambled fixed-orbit predictions;
- constant-RV sources processed through the same visit machinery;
- deliberately incorrect source associations to verify identity gates fail;
- synthetic blended and double-lined spectra;
- synthetic detached and Roche-overflowing binaries;
- injected cross-survey RV zero-point offsets;
- duplicated same-night exposures to verify they do not inflate independent epoch counts.

## Planned figures

1. cohort construction and attrition flow diagram;
2. distribution of minimum-companion-mass q16 before and after Gaia quality gates;
3. mass q16 versus Gaia orbit significance, marked by contamination and geometry status;
4. DESI source-association and epoch-coverage selection function;
5. Delta chi-square versus phase coverage for scorable systems;
6. representative orbit-support and orbit-rejection examples, only after source release approval;
7. Roche filling factor versus minimum companion mass;
8. spectral and SED multiplicity evidence for the final audited subset.

## Planned tables

1. frozen cohort and query provenance;
2. stage definitions and thresholds;
3. attrition matrix;
4. DESI coverage and visit-count distribution;
5. orbit-validation population statistics;
6. candidate-safe follow-up-stage counts;
7. source-level audited table only if release is approved.

## Interpretation matrix

### Strong positive result

At least one source has robust Gaia quality, a constrained primary mass, high q16 minimum companion mass, detached geometry, no strong luminous-companion evidence, three or more clean DESI visits with useful phase coverage, and strong absolute and relative support for the fixed Gaia orbit.

Permitted language: “high-priority compact-object companion candidate,” still conditional on the unresolved alternative models and external review.

### Mixed result

DESI validates some orbital variability but masses or contaminant tests remain ambiguous.

Permitted language: “independently supported binary orbit requiring dedicated stellar and multiplicity modelling.”

### Orbit-rejection result

DESI visits strongly disagree with the fixed Gaia orbit or favor a constant velocity.

Permitted language: “independent spectroscopy challenges the published Gaia orbital interpretation for this source or source association.”

### Coverage-null result

Few or no cohort members possess usable DESI visits.

Permitted language: “the DESI DR1 MWS public single-exposure products provide limited independent validation coverage for this frozen Gaia high-mass SB1 cohort.”

### Population-null result

No system survives all quality, geometry, contamination, and independent-orbit gates.

Permitted language: “the apparent Gaia-only high-minimum-mass tail is substantially reduced by independent validation and physical-consistency requirements.”

## Release and priority policy

- Source-level overlap, DR2 bridges, TARGETIDs, epochs, orbit scores, and dossiers remain encrypted until a release decision.
- Public commits preserve methods, candidate-safe aggregates, hashes, and null results.
- Candidate cards use keyed blinded identifiers by default.
- A public source table requires duplicate literature searches, evidence-card review, and explicit approval.
- No press, immigration, hiring, or social-impact claim may exceed the scientific claim tier supported by the evidence.

## Current frozen result incorporated into the manuscript

Encrypted relay run `29898126651` established the first candidate-safe Gaia-only population result:

- 5,000 Gaia systems in the frozen cohort;
- 2,283 scored primary-mass and correlated minimum-companion-mass products;
- 270 Gaia-quality-passed systems with q16 minimum mass at least 3 solar masses;
- 200 of those without the strongest available Gaia-side contamination category;
- zero independently scored DESI orbits in that run.

These counts motivate the external-validation experiment but do not define a candidate catalogue.

## Completion criteria for HOU-COMPACT I

The first paper is analysis-complete when all of the following exist:

- immutable Gaia cohort and verified covariance audit;
- full primary-mass and minimum-companion-mass products with failure accounting;
- Gaia-side contamination and Roche-geometry audits;
- completed dual-path DESI source-association experiment;
- exact epoch and independent-visit accounting;
- fixed-orbit validation or a rigorously documented validation-coverage null;
- pre-specified sensitivity analyses;
- candidate-safe aggregate tables and figures;
- reproducible manuscript build and archived release bundle.
