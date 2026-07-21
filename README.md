# HOU-COMPACT

**Gaia × DESI search for quiescent compact-object companions**

HOU-COMPACT is a reproducible search for stars whose astrometric and spectroscopic motion may be explained by an unseen compact companion: a black hole, neutron star, or massive white dwarf.

## Core question

Can independent DESI DR1 radial-velocity visits confirm, reject, or substantially re-rank Gaia DR3 single-lined spectroscopic-binary solutions that imply unusually massive and faint companions?

## Why this project is distinct

This is a Galactic stellar-dynamics project. It does not rely on galaxy-image morphology or strong-lensing selection. The primary observables are orbital motion, parallax, radial velocity, stellar parameters, and spectral evidence for contaminating luminous companions.

## Falsifiable hypotheses

1. A small, measurable subset of Gaia DR3 SB1/SB1C systems will show independent DESI visits consistent with the published orbital phase and amplitude.
2. Most apparently massive dark companions will be downgraded after accounting for bad orbital solutions, blends, luminous secondary stars, triples, stripped stars, and survey-specific RV systematics.
3. After strict validation, a ranked tail may remain whose minimum-companion-mass distribution is difficult to reconcile with ordinary luminous binaries.

## Primary data

- Gaia DR3 `gaia_source`
- Gaia DR3 `nss_two_body_orbit`
- Gaia DR3 `astrophysical_parameters`
- DESI DR1 MWS stellar VAC coadded measurements
- DESI DR1 MWS single-exposure RVSpecFit measurements, aggregated into independent visits
- Public photometry, catalogues, and literature services used for contamination and novelty checks

Official documentation:

- https://gea.esac.esa.int/archive/documentation/GDR3/
- https://data.desi.lbl.gov/doc/releases/dr1/vac/mws/
- https://desi-mws-dr1-datamodel.readthedocs.io/en/latest/

## Evidence standard

No object will be called a compact-object candidate from a large inferred mass alone. A serious claim-audit package must survive:

- Gaia spectroscopic-orbit quality and flag audits;
- DESI independent-visit fixed-orbit consistency tests;
- stellar-mass inference with propagated covariance;
- an independently supported primary-star mass;
- luminous-secondary and blend checks using spectra and SEDs;
- alternative hierarchical-multiple and stripped-star hypotheses;
- catalogue and literature crossmatching;
- duplicate-safe final evidence assembly;
- reproducible private candidate-card generation.

The strongest software status is `claim_audit_ready_not_classified`. The pipeline never authorizes an astrophysical classification.

## Work packages

- **WP0 — Data contract and reproducibility**
- **WP1 — Gaia SB1/SB1C seed catalogue**
- **WP2 — DESI exposure extraction, visit construction, and quality control**
- **WP3 — Independent orbit/RV consistency likelihood**
- **WP4 — Minimum-mass and inclination-sensitivity products**
- **WP5 — Contaminant rejection**
- **WP6 — Evidence assembly, novelty audit, ranked follow-up catalogue, and paper**

## Current status

Project initialized on **2026-07-21**.

- [x] Scientific target and falsifiable hypotheses fixed
- [x] Public-code and private-evidence repository policy initialized
- [x] Corrected Gaia v6 query restricted to pure `SB1` and `SB1C`
- [x] Gaia covariance vector, bit index, period confidence, flags, RV-transit counts, and blend diagnostics preserved
- [x] Official SB1/SB1C `bit_index` validation and sparse fixed-length `corr_vec` decoding implemented
- [x] Optional independent DPAC `nsstools` covariance-parity adapter implemented
- [x] Correlation-aware physical Monte Carlo implemented with explicit covariance repair audit
- [x] GSP-Phot gravity/radius inputs preserved for a triage-only M1 proxy
- [x] Independent primary-mass consensus and tension diagnostics implemented
- [x] Deterministic Gaia source-ID to DESI HEALPix file planner implemented
- [x] Metadata-only DESI overlap probe and seed-density prioritization implemented
- [x] Byte-bounded selective DESI downloader and row-aligned extractor implemented
- [x] Close DESI exposures grouped into independent visits by default
- [x] Within-visit disagreement inflates the visit RV uncertainty
- [x] Fixed-Gaia-orbit versus constant-RV validation counts visits instead of raw spectra
- [x] Robust bracketed Kepler solver passed the post-fix synthetic audit
- [x] Edge-on minimum-mass Monte Carlo implemented
- [x] Isotropic-inclination sensitivity product implemented and explicitly labelled
- [x] Gaia-side WP5 blend, structure, contamination, and variability audit implemented
- [x] Conservative one- versus two-component spectral evidence implemented and software-audited
- [x] Conservative single- versus composite-SED evidence implemented and software-audited
- [x] Explicit SIMBAD/VizieR/ADS novelty-coverage and precedence reduction implemented and software-audited
- [x] Final claim-readiness state machine implemented and software-audited
- [x] Duplicate-safe final evidence assembly implemented and passed post-fix CI
- [x] Pseudonymized private candidate-card generator implemented; generated cards remain outside the public repository
- [x] CI failure diagnostics are preserved as downloadable artifacts
- [x] Failure-persistent private pilot workflow records complete or partial run packages
- [ ] Gaia v6 seed query successfully returned and immutably persisted by the current private pilot
- [ ] Live Gaia `corr_vec` serialization validated against DPAC reconstruction on returned rows
- [ ] DESI overlap quantified from returned Gaia source IDs
- [ ] First real independent multi-visit orbit-consistency score produced
- [ ] Real source-level spectral, SED, hierarchy, stripped-star, independent-primary, and novelty audits completed
- [ ] Any source reaches `claim_audit_ready_not_classified`

## Reproducible core run order

```bash
python scripts/run_gaia_query.py \
  --query queries/gaia_sb1_contamination_pilot_v6.adql \
  --output outputs/gaia_sb1_contamination_pilot_v6.ecsv

python scripts/audit_corr_vec_reference.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  --output outputs/corr_vec_reference_audit.csv

python scripts/prepare_primary_mass_priors.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  --output outputs/primary_mass_priors.csv

python scripts/infer_mass_posteriors_correlated.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  --primary-masses outputs/primary_mass_priors.csv \
  --output outputs/mass_posteriors_correlated.csv

python scripts/audit_gaia_contamination.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  --output outputs/gaia_contamination_audit.csv

python scripts/plan_desi_files.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  --output outputs/desi_single_epoch_plan.csv

python scripts/probe_desi_files.py \
  outputs/desi_single_epoch_plan.csv \
  --output outputs/desi_probe.csv

python scripts/prioritize_desi_probe.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  outputs/desi_probe.csv \
  --output outputs/desi_probe_prioritized.csv

python scripts/acquire_desi_epochs.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  outputs/desi_probe_prioritized.csv \
  --output outputs/desi_epochs.csv

python scripts/score_orbit_consistency.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  outputs/desi_epochs.csv \
  --output outputs/orbit_consistency.csv \
  --min-clean-epochs 3 \
  --maximum-visit-gap-hours 2

python scripts/build_followup_triage.py \
  outputs/gaia_sb1_contamination_pilot_v6.ecsv \
  outputs/orbit_consistency.csv \
  outputs/primary_mass_priors.csv \
  outputs/mass_posteriors_correlated.csv \
  --contamination outputs/gaia_contamination_audit.csv \
  --output outputs/followup_triage.csv
```

Final source-level evidence is assembled separately from private spectral, SED, primary-star, alternative-hypothesis, and novelty tables:

```bash
python scripts/build_claim_evidence.py \
  outputs/followup_triage.csv \
  --evidence spectral=private/spectral_evidence.csv \
  --evidence sed=private/sed_evidence.csv \
  --evidence primary=private/independent_primary.csv \
  --evidence alternatives=private/alternative_hypotheses.csv \
  --evidence novelty=private/novelty_audit.csv \
  --output private/merged_claim_evidence.csv
```

See `docs/RESEARCH_PLAN.md`, `docs/DATA_CONTRACT.md`, `docs/WP2_DESI_FILE_PLAN.md`, `docs/WP3_ORBIT_VALIDATION_PROTOCOL.md`, `docs/WP4_MASS_INFERENCE_PROTOCOL.md`, `docs/WP5_CONTAMINANT_REJECTION_PROTOCOL.md`, `docs/WP6_CLAIM_READINESS_PROTOCOL.md`, `docs/WP6_NOVELTY_PROTOCOL.md`, `docs/WP6_EVIDENCE_ASSEMBLY.md`, and `audits/CI_HISTORY.md`.

## Repository policy

All code, queries, tests, experiment manifests, negative results, candidate revisions, and manuscript changes are versioned. Raw survey data and novelty-sensitive candidate cards are not committed to the public repository; immutable URLs, checksums, query text, and derived compact summaries are recorded instead. Candidate-sensitive evidence belongs in the private evidence vault.
