# HOU-COMPACT

**Gaia × DESI search for quiescent compact-object companions**

HOU-COMPACT is a reproducible search for stars whose astrometric and spectroscopic motion is best explained by an unseen compact companion: a black hole, neutron star, or massive white dwarf.

## Core question

Can independent DESI DR1 epoch radial velocities confirm, reject, or substantially re-rank Gaia DR3 non-single-star solutions that imply unusually massive and faint companions?

## Why this project is distinct

This is a Galactic stellar-dynamics project. It does not rely on galaxy-image morphology or strong-lensing selection. The primary observables are orbital motion, parallax, radial velocity, stellar parameters, and spectral evidence for contaminating luminous companions.

## Falsifiable hypotheses

1. A small, measurable subset of Gaia DR3 astrometric/SB1 systems will show DESI epoch velocities consistent with the published orbital phase and amplitude.
2. Most apparently massive dark companions will be downgraded after accounting for bad orbital solutions, blends, luminous secondary stars, triples, stripped stars, and survey-specific RV systematics.
3. After strict validation, a ranked tail will remain whose companion-mass posterior is difficult to reconcile with ordinary main-sequence binaries.

## Primary data

- Gaia DR3 `gaia_source`
- Gaia DR3 `nss_two_body_orbit`
- Gaia DR3 `nss_acceleration_astro` where useful
- DESI DR1 MWS stellar VAC coadded measurements
- DESI DR1 MWS single-epoch RVSpecFit measurements
- Public photometry/crossmatches used only for contamination checks

Official documentation:

- https://gea.esac.esa.int/archive/documentation/GDR3/
- https://data.desi.lbl.gov/doc/releases/dr1/vac/mws/
- https://desi-mws-dr1-datamodel.readthedocs.io/en/latest/

## Evidence standard

No object will be called a compact-object candidate from a large inferred mass alone. A candidate must survive:

- astrometric/orbital quality cuts;
- DESI epoch-level RV consistency tests;
- stellar-mass inference with propagated uncertainty;
- luminous-secondary and blend checks;
- alternative triple/stripped-star hypotheses;
- catalogue and literature crossmatching;
- reproducible candidate-card generation.

## Work packages

- **WP0 — Data contract and reproducibility**
- **WP1 — Gaia seed catalogue**
- **WP2 — DESI epoch extraction and quality control**
- **WP3 — Orbit/RV consistency likelihood**
- **WP4 — Companion-mass posterior**
- **WP5 — Contaminant rejection**
- **WP6 — Ranked candidate catalogue and paper**

## Current status

Project initialized on **2026-07-21**.

- [x] Scientific target fixed
- [x] Repository initialized
- [x] Data products and first-pass schema identified
- [ ] Gaia seed query executed
- [ ] DESI crossmatch executed
- [ ] First validated candidate ranking

See `docs/RESEARCH_PLAN.md` and `docs/DATA_CONTRACT.md` for the operating specification.

## Repository policy

All code, queries, tests, experiment manifests, negative results, candidate revisions, and manuscript changes are versioned here. Raw survey data are not committed; immutable URLs, checksums, query text, and derived compact tables are recorded instead.
