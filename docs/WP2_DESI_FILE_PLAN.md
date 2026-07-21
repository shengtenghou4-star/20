# WP2 — DESI single-epoch overlap and extraction plan

Frozen: 2026-07-21

## Purpose

Identify which Gaia DR3 SB1 seed systems fall in DESI DR1 MWS single-epoch files before downloading bulk FITS products. The overlap probe is metadata-only: it checks whether a predicted public file exists and records size/provenance headers. It does not rank or label astrophysical candidates.

## Official data facts used

1. Gaia DR3 `source_id` encodes a nested HEALPix index. At level `n`, the index is obtained by integer division by `2^(59-2n)`. DESI MWS single-epoch products use NSIDE=64, nested, which is HEALPix level 6.
2. DESI DR1 MWS run `240521` contains individual-exposure RVSpecFit measurements.
3. Per-pixel files follow the documented pattern:

   `rv_output/240521/healpix/{survey}/{program}/{healpix//100}/{healpix}/rvtab_spectra-{survey}-{program}-{healpix}.fits`

4. Each single-epoch FITS product contains row-aligned `RVTAB`, `FIBERMAP`, `SCORES`, and `GAIA` extensions. `RVTAB` supplies `VRAD`, `VRAD_ERR`, `RVS_WARN`, `SUCCESS`, `TARGETID`, `EXPID`, S/N, and the NSIDE=64 `HEALPIX`; `FIBERMAP` supplies `MJD`, `NIGHT`, `FIBERSTATUS`, and a second `TARGETID`; `GAIA` supplies Gaia DR3 `SOURCE_ID`.
5. The DESI release documentation flags systematic radial-velocity errors in the backup program. Backup rows remain marked and cannot support a scientific claim until the published correction is explicitly implemented and tested.

Official references:

- https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html
- https://data.desi.lbl.gov/doc/releases/dr1/vac/mws/
- https://desi-mws-dr1-datamodel.readthedocs.io/en/latest/rv_output/index.html
- https://desi-mws-dr1-datamodel.readthedocs.io/en/latest/rv_output/RVRUN/rvpix_exp.html

## Pipeline

1. Execute `queries/gaia_sb1_mass_proxy_pilot_v2.adql` and preserve the exact query hash.
2. Convert unique Gaia source IDs to level-6 nested HEALPix IDs.
3. Generate deterministic URLs for `main/bright`, `main/dark`, and `main/backup`.
4. Probe URLs with bounded retries; save HTTP status, content length, ETag, and Last-Modified.
5. Download only existing per-pixel files that contain at least one seed source.
6. Extract rows by `GAIA.SOURCE_ID`, verify extension lengths and `TARGETID` alignment, then preserve all raw warning and quality fields.
7. Apply a conservative first-pass quality mask. No object advances to orbit fitting from a failed, warned, bad-fiber, non-finite, or unconstrained RV epoch.

## Gate B acceptance criteria

- The focused Gaia SB1 query executes and its live schema is validated.
- Every file-plan row is reproducible from a Gaia source ID.
- URL-probe output and manifests have SHA256 checksums.
- At least one existing DESI single-epoch file is located, or the null overlap is documented quantitatively.
- FITS extension row alignment and `TARGETID` identity are tested before extraction.
- The number of seed sources with 0, 1, 2, and 3+ clean DESI epochs is reported.
- Backup-program rows are separated from uncorrected main bright/dark rows.

## Scientific interpretation boundary

A DESI overlap is not evidence for a compact object. A large RV change is not evidence for a black hole. Gate B only establishes independent epoch measurements and their quality. Orbit consistency, stellar-mass inference, luminous-secondary rejection, and alternative triple/stripped-star models remain mandatory later gates.
