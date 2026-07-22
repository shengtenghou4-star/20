# HOU-COMPACT candidate-safe result — run 29916105258

Frozen: 2026-07-22  
Scientific status: **validated DESI DR1 MWS coverage null for the frozen Gaia v9 cohort**  
Claim boundary: no source-level identifiers or compact-object classifications are released here.

## Execution status

The complete encrypted relay finished successfully. The run executed the frozen 5,000-source Gaia v9 cohort through:

- Gaia covariance-reference validation;
- primary-star and correlated minimum-companion-mass inference;
- Gaia-side contamination audit;
- periastron Roche-geometry audit;
- official NOIRLab Data Lab Gaia DR3–DESI DR1 zpix association;
- Gaia DR3-to-DR2 neighbourhood bridging;
- exact DESI TARGETID and Gaia DR2 `G2/REF_ID` extraction paths;
- independent-visit/orbit scoring logic;
- stage attrition, selection-bias, and 54-configuration sensitivity reports;
- encrypted source-level persistence.

Workflow run: `29916105258`  
Encrypted artifact: `hou-compact-encrypted-v2-29916105258-attempt-1`  
Artifact ID: `8528352594`  
Artifact digest: `sha256:8aecd5ac4a2f7c86b3fc44b26c7bb9d70f4cdfa69b36f9854db3458905d02a5b`

## Frozen cohort and Gaia-side products

- Gaia systems: **5,000**.
- Covariance-reference audit: **250/250 passed**.
- Primary-mass and correlated minimum-mass products scored: **2,283**.
- Missing or unusable stellar inputs: **2,717**; these are not astrophysical rejections.
- Primary-mass-scored fraction: **0.4566**.
- No audited field reached the frozen moderate-or-large scored-versus-unscored distribution-shift threshold.

Minimum-companion-mass lower-quantile strata among finite mass products:

- q16 ≥ 1.4 solar masses: **1,770**;
- q16 ≥ 3 solar masses: **284**;
- q16 ≥ 5 solar masses: **57**;
- q16 ≥ 8 solar masses: **16**.

These are descriptive follow-up strata, not compact-object classifications.

## Roche-geometry result

- detached geometry consistent: **2,249**;
- geometry inconsistent: **18**;
- near or overflowing Roche lobe: **16**;
- input error: **2,717**.

Roche consistency is necessary but not sufficient for a detached dark-companion interpretation.

## Dual-path DESI source-association experiment

### Path A — official Data Lab DR3-to-DESI zpix association

The 5,000 Gaia DR3 source IDs were queried in 34 bounded batches against the official Gaia DR3–DESI DR1 zpix convenience crossmatch. Every batch completed successfully and returned a valid header-only CSV response.

- input Gaia sources: **5,000**;
- exact overlap rows: **0**;
- matched Gaia sources: **0**;
- mapped DESI TARGETIDs: **0**;
- mapped DESI files: **0**.

Exact-overlap output SHA256: `23d543a56e2111de0f879bc20c72b6ab912f3b12f70ca2260e29fd41f796b531`.

### Path B — Gaia DR3-to-DR2 bridge plus exact DESI REF_ID

The official Gaia `dr2_neighbourhood` table returned 5,075 neighbour rows for all 5,000 DR3 sources. The frozen distance and ambiguity audit accepted one DR2 bridge for every source.

- accepted DR3-to-DR2 bridges: **5,000/5,000**;
- sources with one neighbour: **4,925**;
- sources with two neighbours: **75**;
- accepted source with margin below 5 mas: **0**;
- maximum accepted nearest-neighbour separation: approximately **59.0 mas**.

Bridge output SHA256: `e7bf9556c18509c061fd4be6fa87655de6ec3eed3bf980c9a28bf6b4b0dc7bc6`.

The extraction then scanned **all 453 verified public main bright/dark MWS single-exposure files** and required exact `FIBERMAP.REF_CAT='G2'` plus integer `REF_ID` equality.

- verified non-backup files scanned: **453/453**;
- files containing an accepted bridge ID: **0**;
- matched Gaia sources: **0**;
- extracted single-exposure rows: **0**.

REF_ID epoch output SHA256: `8e984a76467564b285ebd34a5770fd45aca34dc325d8d2bf8cdc238118643795`.

## Orbit-validation and attrition result

Because neither authoritative identity path yielded a DESI single-exposure measurement:

- independently scorable Gaia orbits: **0**;
- first-stage Gaia-quality holds: **406**;
- systems reaching and then held at the DESI-orbit gate: **4,594**;
- systems passing all current evidence gates: **0**.

All **54** frozen triage-sensitivity configurations also returned zero systems passing all evidence gates. This stability reflects absence of independent DESI visits, not evidence against the Gaia binaries themselves.

## Scientific interpretation

This run establishes a real survey-selection result rather than a software failure:

> The public DESI DR1 MWS single-exposure products provide no exact source-level validation coverage for the frozen 5,000-source Gaia v9 high-mass SB1-family cohort under either the official DR3-to-zpix association or the independent DR3-to-DR2-to-`G2/REF_ID` identity chain.

The result does **not** imply that the Gaia systems are spurious, that no compact companions exist, or that DESI has no spectra near their sky positions. It says that the frozen cohort has zero authoritative source overlap with the verified public DESI MWS single-exposure products used by this experiment.

## Consequence for HOU-COMPACT

The DESI experiment is complete and remains a publishable coverage/selection-function result. Independent orbital validation now moves to surveys with substantially broader multi-epoch stellar coverage, beginning with the LAMOST DR8 multiple-epoch catalog and retaining APOGEE DR17 as a secondary path.

The Gaia cohort, mass products, physical-consistency gates, visit aggregation, fixed-orbit scorer, negative controls, and candidate-safe reporting remain unchanged. A later spectroscopy extension receives a distinct work-package and data-contract version; it cannot silently replace this DESI result.
