# HOU-COMPACT

**Gaia × DESI search for quiescent compact-object companions**

HOU-COMPACT is a reproducible search for stars whose astrometric and spectroscopic motion is best explained by an unseen compact companion: a black hole, neutron star, or massive white dwarf.

## Core question

Can independent DESI DR1 epoch radial velocities confirm, reject, or substantially re-rank Gaia DR3 single-lined spectroscopic-binary solutions that imply unusually massive and faint companions?

## Why this project is distinct

This is a Galactic stellar-dynamics project. It does not rely on galaxy-image morphology or strong-lensing selection. The primary observables are orbital motion, parallax, radial velocity, stellar parameters, and spectral evidence for contaminating luminous companions.

## Falsifiable hypotheses

1. A small, measurable subset of Gaia DR3 SB1/SB1C systems will show DESI epoch velocities consistent with the published orbital phase and amplitude.
2. Most apparently massive dark companions will be downgraded after accounting for bad orbital solutions, blends, luminous secondary stars, triples, stripped stars, and survey-specific RV systematics.
3. After strict validation, a ranked tail will remain whose minimum-companion-mass distribution is difficult to reconcile with ordinary luminous binaries.

## Primary data

- Gaia DR3 `gaia_source`
- Gaia DR3 `nss_two_body_orbit`
- DESI DR1 MWS stellar VAC coadded measurements
- DESI DR1 MWS single-epoch RVSpecFit measurements
- Public photometry and catalogues used for contamination and novelty checks

Official documentation:

- https://gea.esac.esa.int/archive/documentation/GDR3/
- https://data.desi.lbl.gov/doc/releases/dr1/vac/mws/
- https://desi-mws-dr1-datamodel.readthedocs.io/en/latest/

## Evidence standard

No object will be called a compact-object candidate from a large inferred mass alone. A candidate must survive:

- Gaia spectroscopic-orbit quality and flag audits;
- DESI epoch-level fixed-orbit consistency tests;
- stellar-mass inference with propagated uncertainty;
- luminous-secondary and blend checks;
- alternative triple and stripped-star hypotheses;
- catalogue and literature crossmatching;
- reproducible candidate-card generation.

## Work packages

- **WP0 — Data contract and reproducibility**
- **WP1 — Gaia SB1/SB1C seed catalogue**
- **WP2 — DESI epoch extraction and quality control**
- **WP3 — Independent orbit/RV consistency likelihood**
- **WP4 — Minimum-mass and inclination-sensitivity products**
- **WP5 — Contaminant rejection**
- **WP6 — Ranked follow-up catalogue and paper**

## Current status

Project initialized on **2026-07-21**.

- [x] Scientific target and falsifiable hypotheses fixed
- [x] Repository and provenance policy initialized
- [x] Gaia v4 query restricted to pure `SB1` and `SB1C`
- [x] Gaia covariance vector, period confidence, flags, and RV-transit counts preserved
- [x] GSP-Phot gravity/radius inputs preserved for a triage-only M1 proxy
- [x] Deterministic Gaia source-ID to DESI HEALPix file planner implemented
- [x] Metadata-only DESI overlap probe implemented
- [x] Byte-bounded selective DESI downloader and row-aligned extractor implemented
- [x] Fixed-Gaia-orbit versus constant-RV validation code implemented
- [x] Edge-on minimum-mass Monte Carlo implemented
- [x] Isotropic-inclination sensitivity product implemented and explicitly labelled
- [x] Transparent follow-up gates implemented without compact-object labels
- [x] Unit tests added for physics, HEALPix, FITS alignment, orbits, mass inference, and triage
- [x] GitHub Actions configured to run tests, Gaia v4 acquisition, WP4 triage products, and DESI overlap probing
- [ ] Gaia v4 seed query successfully returned from the live archive
- [ ] DESI overlap quantified from returned Gaia source IDs
- [ ] First real multi-epoch orbit-consistency score produced
- [ ] Gaia `corr_vec` propagated into the orbital uncertainty model
- [ ] Luminous-secondary, hierarchy, stripped-star, and novelty audits completed

## Reproducible run order

```bash
python scripts/run_gaia_query.py \
  --query queries/gaia_sb1_mass_proxy_pilot_v4.adql \
  --output outputs/gaia_sb1_mass_proxy_pilot_v4.ecsv

python scripts/prepare_primary_mass_priors.py \
  outputs/gaia_sb1_mass_proxy_pilot_v4.ecsv \
  --output outputs/primary_mass_priors.csv

python scripts/infer_mass_posteriors.py \
  outputs/gaia_sb1_mass_proxy_pilot_v4.ecsv \
  --primary-masses outputs/primary_mass_priors.csv \
  --output outputs/mass_posteriors.csv

python scripts/plan_desi_files.py \
  outputs/gaia_sb1_mass_proxy_pilot_v4.ecsv \
  --output outputs/desi_single_epoch_plan.csv

python scripts/probe_desi_files.py \
  outputs/desi_single_epoch_plan.csv \
  --output outputs/desi_probe.csv

python scripts/acquire_desi_epochs.py \
  outputs/gaia_sb1_mass_proxy_pilot_v4.ecsv \
  outputs/desi_probe.csv \
  --output outputs/desi_epochs.csv

python scripts/score_orbit_consistency.py \
  outputs/gaia_sb1_mass_proxy_pilot_v4.ecsv \
  outputs/desi_epochs.csv \
  --output outputs/orbit_consistency.csv

python scripts/build_followup_triage.py \
  outputs/gaia_sb1_mass_proxy_pilot_v4.ecsv \
  outputs/orbit_consistency.csv \
  outputs/primary_mass_priors.csv \
  outputs/mass_posteriors.csv \
  --output outputs/followup_triage.csv
```

See `docs/RESEARCH_PLAN.md`, `docs/DATA_CONTRACT.md`, `docs/WP2_DESI_FILE_PLAN.md`, `docs/WP3_ORBIT_VALIDATION_PROTOCOL.md`, and `docs/WP4_MASS_INFERENCE_PROTOCOL.md`.

## Repository policy

All code, queries, tests, experiment manifests, negative results, candidate revisions, and manuscript changes are versioned here. Raw survey data are not committed; immutable URLs, checksums, query text, and derived compact tables are recorded instead.
