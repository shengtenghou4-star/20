# WP2 broad-coverage protocol for DESI single-exposure validation

Frozen: 2026-07-22

## Motivation

The initial private pilot limited acquisition to 12 DESI per-HEALPix files. Candidate-safe
metadata from the live probe showed that this limit was unnecessarily narrow: 618 files
existed for the 5,000-source Gaia seed cohort, including 453 non-backup files in 265
HEALPix cells. Their aggregate declared size was far below the existing 2 GiB downloader
ceiling. The narrow batch also spent multiple slots on backup-program files that are
excluded from orbit scoring until the published backup RV correction is implemented.

A separate coverage audit found that only five of the first 500 mass-scored Gaia rows
fell in non-backup DESI-covered cells. Therefore limiting mass inference to the first 500
rows and limiting DESI acquisition to 12 files created a strong avoidable intersection
bottleneck even before any astrophysical quality gate was applied.

These are aggregate coverage diagnostics only. No source identifier or candidate-level
mass is disclosed by this protocol.

## Revised bounded pilot

The next encrypted pilot will:

1. rank every existing non-backup file ahead of uncorrected backup files;
2. retain Gaia seed density as the tie-breaker within usable programs;
3. acquire up to 500 non-backup files while preserving the 2 GiB total download ceiling
   and per-file size limit;
4. infer preliminary primary and companion-mass products for all 5,000 seed rows using
   2,000 Monte Carlo draws per pilot product;
5. continue to aggregate closely spaced exposures into independent visits before orbit
   scoring;
6. keep every source-level table encrypted and publish only aggregate counts and statuses.

## Selection-function boundary

The broader file budget is a coverage correction, not a candidate-ranking mechanism.
Files are selected only from public coverage metadata and seed density; no companion-mass
posterior, orbit score, contamination flag, or source identity influences acquisition.
This prevents the live validation set from being conditioned on the desired outcome.

## Acceptance criteria

- all non-backup files that fit within the hard byte ceiling are attempted before backup;
- downloaded files retain URL, checksum, size, survey, program, and HEALPix provenance;
- Gaia-to-DESI matches retain match mode and angular separation;
- MJD/NIGHT come from FIBERMAP and SN_B/SN_R/SN_Z from RVTAB;
- same-night or closely spaced exposures are collapsed into independent visits;
- orbit scoring reports explicit null coverage rather than silently dropping unmatched rows;
- no compact-object interpretation is permitted before orbit support, primary-mass
  validation, and luminous-secondary/hierarchy rejection.
