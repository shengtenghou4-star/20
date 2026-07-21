# Data Contract v0.1

This file defines the minimum provenance and normalized columns required before a table may enter scientific analysis.

## Official sources

### Gaia DR3

Documentation root:

- https://gea.esac.esa.int/archive/documentation/GDR3/

Primary tables:

- `gaiadr3.gaia_source`
- `gaiadr3.nss_two_body_orbit`
- `gaiadr3.nss_acceleration_astro` when introduced later

Important Gaia facts for implementation:

- One `source_id` can have more than one independent NSS solution, so `source_id` alone is not a unique row key.
- `nss_solution_type` determines which orbital fields are populated.
- `significance` is solution-type dependent: for astrometric systems it reflects the semi-major-axis significance; for spectroscopic systems it reflects primary semi-amplitude divided by uncertainty.
- `goodness_of_fit` and `efficiency` measure different failure modes and must remain separate.

Normalized Gaia key:

`(source_id, nss_solution_type, solution_id)`

Required Gaia columns:

- `source_id`
- `solution_id`
- `nss_solution_type`
- `ra`, `dec`
- `parallax`, `parallax_error`
- `period`, `period_error`
- `t_periastron`, `t_periastron_error`
- `eccentricity`, `eccentricity_error`
- `arg_periastron`, `arg_periastron_error`
- `center_of_mass_velocity`, `center_of_mass_velocity_error`
- `semi_amplitude_primary`, `semi_amplitude_primary_error`
- `a_thiele_innes`, `b_thiele_innes`, `f_thiele_innes`, `g_thiele_innes`
- `goodness_of_fit`
- `efficiency`
- `significance`
- `flags`
- selected `gaia_source` photometry and astrometric diagnostics

Null values are expected and interpreted through `nss_solution_type`; they must not be silently imputed.

### DESI DR1 MWS VAC

Release page:

- https://data.desi.lbl.gov/doc/releases/dr1/vac/mws/

Data model:

- https://desi-mws-dr1-datamodel.readthedocs.io/en/latest/

Release root:

- https://data.desi.lbl.gov/public/dr1/vac/dr1/mws/iron/v1.0/

Core products:

- coadded catalogue: `mwsall-pix-iron.fits`
- single-epoch RVSpecFit products under `rv_output/240521/`

The release documentation reports more than ten million single-epoch measurements and more than 1.7 million Gaia sources with multiple radial-velocity/stellar-parameter measurements.

Required DESI epoch columns, subject to direct schema verification:

- stable target/source identifier and Gaia crossmatch identifier
- `TARGETID`
- observation time identifier (`MJD`, night, or equivalent fields available in the epoch table)
- `VRAD`
- `VRAD_ERR`
- `RVS_WARN`
- `SUCCESS`
- `SN_B`, `SN_R`, `SN_Z` or equivalent epoch S/N fields
- `SURVEY`
- `PROGRAM`
- `HEALPIX`
- stellar parameters used for quality and visible-star inference

Important release warning:

- The official DR1 page identifies systematic radial-velocity errors in the backup program. The correction specified by the release paper must be implemented and tested before those measurements are used.

## Local normalized tables

### `gaia_nss_seed.parquet`

One row per Gaia NSS solution. Required metadata sidecar:

- ADQL query SHA256
- query execution timestamp
- Gaia release identifier
- downloaded table SHA256
- row count

### `desi_epochs.parquet`

One row per accepted or rejected DESI epoch. Rejected rows stay present with a reason code.

Required normalized fields:

- `gaia_source_id`
- `targetid`
- `epoch_id`
- `time_mjd`
- `vrad_kms`
- `vrad_err_kms`
- `survey`
- `program`
- `sn_b`, `sn_r`, `sn_z`
- `rvs_warn`
- `success`
- `rv_correction_kms`
- `accepted_epoch`
- `epoch_rejection_code`
- source file URL and checksum

### `candidate_evidence.parquet`

One row per Gaia NSS solution after joining and inference.

Mandatory fields:

- Gaia normalized key
- DESI usable epoch count
- constant-RV chi-square and dof
- maximum pairwise RV significance
- Gaia-orbit predictive likelihood where available
- visible-star mass posterior summary
- companion-mass posterior summary
- luminous-secondary probability or diagnostic
- contaminant flags
- novelty-audit state
- candidate tier
- pipeline Git SHA

## Reason-code policy

Reason codes are append-only and machine readable. Initial namespace:

- `GAIA_LOW_SIGNIFICANCE`
- `GAIA_BAD_GOF`
- `GAIA_LOW_EFFICIENCY`
- `GAIA_FLAGGED`
- `DESI_RVS_WARN`
- `DESI_LOW_SNR`
- `DESI_BAD_EPOCH`
- `DESI_BACKUP_UNCORRECTED`
- `CROSSMATCH_AMBIGUOUS`
- `SPECTRUM_COMPOSITE`
- `LIKELY_SB2`
- `BLEND_RISK`
- `TRIPLE_PLAUSIBLE`
- `VISIBLE_STAR_MODEL_UNSTABLE`
- `ORBIT_RV_INCONSISTENT`
- `KNOWN_OBJECT`

A candidate may carry multiple reason codes. No row is deleted merely because it fails a filter.
