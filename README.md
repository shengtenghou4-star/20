# HOU-COMPACT

**Gaia orbital solutions × independent multi-epoch spectroscopy**

HOU-COMPACT is a reproducible search for stars whose orbital motion may be explained by an unseen compact companion: a black hole, neutron star, or massive white dwarf. The project is deliberately fail-closed: a large Gaia-only mass estimate is never treated as a compact-object classification.

## Core question

How many apparently massive, unseen companions in the Gaia DR3 SB1/SB1C orbital catalogue survive reproducible orbital-quality, stellar-parameter, geometry, multiplicity, and independent radial-velocity tests?

The first external-spectroscopy experiment used DESI DR1 MWS. It is now complete and produced a rigorously validated **coverage null** for the frozen 5,000-source Gaia v9 cohort. The next validation extension targets broader stellar multi-epoch surveys, beginning with LAMOST DR8 and retaining APOGEE DR17 as a secondary path.

## Evidence standard

No object is called a compact-object candidate from a large inferred mass alone. A serious evidence package must survive:

- Gaia orbital quality, flags, and covariance audits;
- an independently constrained primary-star mass;
- correlated minimum-companion-mass inference;
- detached Roche geometry;
- authoritative source association to an external spectroscopic survey;
- multiple independent visits with useful phase coverage;
- fixed-Gaia-orbit versus constant-velocity comparison;
- spectral, SED, blend, hierarchy, and stripped-star alternatives;
- catalogue and literature novelty review;
- duplicate-safe private evidence assembly.

The strongest software state remains `claim_audit_ready_not_classified`. The pipeline never authorizes an astrophysical classification.

## Frozen Gaia cohort

Primary cohort: 5,000 Gaia DR3 `SB1`, `SB1C`, and `AstroSpectroSB1` solutions returned by the versioned v9 query.

Current Gaia-side aggregate results:

- 5,000 systems acquired with complete query provenance;
- 250/250 covariance-reference checks passed;
- 2,283 primary-mass and correlated minimum-mass products scored;
- 2,717 rows remain input-error cases rather than astrophysical rejections;
- q16 minimum-companion-mass counts: 1,770 at or above 1.4 solar masses, 284 at or above 3, 57 at or above 5, and 16 at or above 8;
- 2,249 systems have detached Roche geometry under the frozen audit;
- 18 are geometry-inconsistent and 16 are near or overflowing their primary Roche lobe.

These are population and follow-up strata, not object classes.

## DESI DR1 result

Encrypted relay run `29916105258` completed the dual-path DESI source-association experiment:

1. official NOIRLab Data Lab Gaia DR3–DESI DR1 zpix association followed by exact `TARGETID` extraction;
2. official Gaia DR3-to-DR2 neighbourhood bridging followed by exact DESI `REF_CAT='G2'` and integer `REF_ID` equality.

Frozen outcome:

- 5,000/5,000 Gaia DR3 sources received accepted Gaia DR2 bridges;
- 34 bounded Data Lab batches completed successfully;
- exact Data Lab overlap rows: 0;
- verified public main bright/dark MWS files scanned through the REF_ID path: 453/453;
- exact DESI epoch rows: 0;
- independently scorable Gaia orbits: 0.

Therefore the public DESI DR1 MWS single-exposure products provide no exact source-level validation coverage for this frozen Gaia cohort. This is a survey-selection result, not evidence that the Gaia binaries are false.

See [`results/CANDIDATE_SAFE_RUN_29916105258.md`](results/CANDIDATE_SAFE_RUN_29916105258.md).

## Work packages

- **WP0 — data contract, provenance, and encrypted evidence**
- **WP1 — Gaia seed catalogue and orbital-quality audit**
- **WP2a — DESI DR1 source association and coverage experiment: complete**
- **WP2b — LAMOST/APOGEE multi-epoch spectroscopy extension: active**
- **WP3 — independent fixed-orbit validation and negative controls**
- **WP4 — primary-star and companion-mass inference**
- **WP5 — contamination and physical-consistency rejection**
- **WP6 — attrition, sensitivity, evidence assembly, and paper**

## Current status

Project initialized on **2026-07-21**.

- [x] Scientific target and claim boundaries frozen
- [x] Public-code and encrypted-evidence repository policy established
- [x] Immutable 5,000-source Gaia v9 cohort acquired
- [x] Gaia covariance reconstructed and checked against the reference adapter
- [x] Primary-mass and correlated minimum-mass inference completed with failure accounting
- [x] Gaia-side blend/multiplicity audit completed
- [x] Periastron Roche-geometry audit completed
- [x] Dual Gaia–DESI identity paths implemented and live-service contracts validated
- [x] All 453 verified non-backup DESI MWS files scanned through the DR2 REF_ID path
- [x] DESI DR1 coverage-null result frozen with hashes and encrypted source-level bundle
- [x] Primary-mass selection-bias audit completed
- [x] Candidate-safe stage attrition and 54-configuration sensitivity reporting completed
- [x] Manuscript questions, evidence stages, figures, tables, and interpretation matrix pre-registered
- [ ] LAMOST DR8 multi-epoch catalogue acquired and release-aware Gaia identity contract validated
- [ ] First real external multi-visit fixed-orbit score produced
- [ ] Final source-level spectral/SED/hierarchy/stripped-star audits completed
- [ ] Any source reaches `claim_audit_ready_not_classified`
- [ ] Reproducible manuscript build and archived release bundle completed

## Reproducible DESI experiment

```bash
python scripts/run_gaia_query.py \
  --mode async \
  --query queries/gaia_sb1_contamination_pilot_v9.adql \
  --output outputs/gaia_seed.ecsv

python scripts/query_desi_gaia_overlap.py \
  outputs/gaia_seed.ecsv \
  --output outputs/desi_gaia_exact_overlap.csv

python scripts/query_gaia_dr2_bridge.py \
  outputs/gaia_seed.ecsv \
  --output outputs/gaia_dr2_bridge.csv

python scripts/acquire_desi_epochs_exact.py \
  outputs/gaia_seed.ecsv \
  outputs/desi_gaia_exact_overlap.csv \
  outputs/desi_probe.csv \
  --output outputs/desi_epochs_targetid.csv

python scripts/acquire_desi_epochs_refid.py \
  outputs/gaia_seed.ecsv \
  outputs/gaia_dr2_bridge.csv \
  outputs/desi_probe.csv \
  --output outputs/desi_epochs_refid.csv
```

Population reporting:

```bash
python scripts/summarize_followup_attrition.py \
  outputs/followup_triage.csv \
  --output outputs/followup_attrition_summary.json

python scripts/run_triage_sensitivity.py \
  outputs/followup_triage.csv \
  --output outputs/triage_sensitivity.csv
```

See `paper/HOU_COMPACT_I_ANALYSIS_PLAN.md` and the versioned protocols under `docs/`.

## Repository policy

All code, queries, tests, manifests, negative results, candidate revisions, and manuscript changes are versioned. Raw survey files and novelty-sensitive source cards are not committed publicly. Candidate-sensitive source IDs, cross-survey identifiers, velocities, mass rows, and dossiers remain in encrypted evidence bundles whose checksums and candidate-safe summaries are preserved separately.
