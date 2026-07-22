# WP2b — LAMOST DR8 multi-epoch identity and timing contract

Frozen: 2026-07-22

## Purpose

The DESI DR1 MWS experiment returned a validated coverage null for the frozen 5,000-source Gaia v9 cohort. HOU-COMPACT therefore extends independent radial-velocity validation to LAMOST DR8 without altering the Gaia cohort, mass inference, orbit model, or evidence thresholds.

The first LAMOST path uses the DR8 v1.0 low-resolution multiple-epoch catalogue because its documentation explicitly identifies `gaia_source_id` as a Gaia DR2 source identifier and reports 2,012,297 multi-observed targets.

## Official catalogue fields used

The multiple-epoch product supplies:

- `source_id`: LAMOST HTM source identifier;
- `gaia_source_id`: Gaia DR2 source identifier;
- `obs_number`: number of observations;
- `obsid_list`: hyphen-delimited spectrum IDs;
- `midmjm_list`: hyphen-delimited local modified Julian minutes at observation middle time;
- `rv_list`: hyphen-delimited radial velocities.

The LAMOST documentation instructs users to join each `obsid` back to the per-spectrum catalogues. HOU-COMPACT requires that join before scoring because the multiple-epoch table does not itself supply a radial-velocity uncertainty.

Official references:

- https://www.lamost.org/dr8/v1.0/doc/lr-data-production-description
- https://www.lamost.org/dr8/v1.0/catalogue
- https://www.lamost.org/dr11/v1.1/doc/faq

## Release-aware identity

1. `gaia_source_id` is treated as Gaia DR2, never Gaia DR3.
2. The catalogue must be loaded with identifier columns as text.
3. Exponent-form identifiers and binary floating values are rejected because they cannot prove exact preservation above 2^53.
4. A LAMOST row is associated with the frozen Gaia cohort only through exact integer equality with an accepted Gaia DR3-to-DR2 bridge.
5. Positional matching may be used as a diagnostic but cannot silently replace the identifier chain.

## List parsing

LAMOST joins list values with `-`. Negative radial velocities therefore appear with doubled hyphens when they follow another value. The parser reconstructs signed values, rejects exponent notation and ambiguous sign sequences, and requires:

`obs_number == len(obsid_list) == len(midmjm_list) == len(rv_list)`.

Duplicate `obsid` values within one source or duplicate DR2-source/obsid pairs across the catalogue fail closed.

## LMJM to UTC MJD

LAMOST records local modified Julian minute in Beijing time, UTC+8. The frozen conversion is:

`UTC MJD = LMJM / 1440 - 8/24`.

This reproduces official header examples. For example, `LMJM=83764590` converts to UTC MJD `58169.520833...`, corresponding to 12:30 UTC and the documented 20:30 Beijing start time.

The low-resolution multiple-epoch field is documented as the middle time of the observation. No barycentric time correction is invented; the catalogue time convention is preserved and recorded.

## Radial-velocity uncertainty and quality gate

An exploded multiple-epoch row remains `measured_without_uncertainty` until exact `obsid` equality joins it to a per-spectrum product containing:

- a finite radial velocity;
- a finite positive `rv_err`;
- relevant S/N and quality fields when available.

The list RV and per-spectrum RV must agree within a frozen tolerance. Disagreement, absent uncertainty, duplicate obsid, sentinel values, or failed quality fields block orbit scoring while preserving the measurement and failure reason.

## Scientific boundary

An exact LAMOST overlap proves source association. Multiple RV measurements prove repeated spectroscopy. Neither establishes the Gaia orbital phase relation or a compact companion. Independent fixed-orbit scoring, phase-scramble controls, primary-mass inference, Roche geometry, luminous-secondary rejection, hierarchy/stripped-star alternatives, and novelty review remain mandatory.
