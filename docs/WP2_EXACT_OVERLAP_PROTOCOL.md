# WP2 exact Gaia–DESI overlap protocol

Frozen: 2026-07-22

## Problem corrected

A DESI per-HEALPix RV file being present in the same NSIDE=64 cell as a Gaia source does **not** establish that the source received a DESI fiber. Positional matching every Gaia seed against every row in an available cell is useful as a diagnostic, but it is not the authoritative source-to-spectrum relationship.

The primary production path therefore uses NOIRLab Astro Data Lab's official 1.5-arcsec nearest-neighbour convenience crossmatch between Gaia DR3 and `desi_dr1.zpix`, then joins the crossmatch's DESI-side identifier to `desi_dr1.zpix.id` to recover `TARGETID`, survey, program, and HEALPix. Exact `TARGETID` equality is authoritative once this mapping exists; membership in the precomputed positional crossmatch is not guaranteed complete for high-proper-motion, blended, crowded, or otherwise difficult sources.

Official references:

- https://datalab.noirlab.edu/data/desi
- https://datalab.noirlab.edu/docs/manual/UsingAstroDataLab/ServiceInterfaces/QueryManager/QueryManager.html
- https://datalab.noirlab.edu/help/index.php?qa=1248
- https://datalab.noirlab.edu/help/index.php?qa=1595
- https://datalab.noirlab.edu/help/index.php?qa=2099

## Exact query contract

For bounded batches of Gaia DR3 source IDs:

```sql
SELECT
    x.id1 AS source_id,
    z.targetid AS targetid,
    z.survey AS survey,
    z.program AS program,
    z.healpix AS healpix,
    x.distance AS match_distance_arcsec
FROM gaia_dr3.x1p5__gaia_source__desi_dr1__zpix AS x
JOIN desi_dr1.zpix AS z ON x.id2 = z.id
WHERE x.id1 IN (...)
  AND z.survey = 'main'
  AND z.program IN ('bright','dark')
```

Data Lab documents the crossmatch `distance` column in arcseconds. Large identifiers are never cast to floating point. Every batch records hashes of the SQL and returned CSV. Any returned source outside the current request batch, missing schema field, non-integral identifier, non-finite distance, or separation above 1.5 arcsec fails closed.

## Exact epoch extraction

1. Intersect crossmatched files with the immutable verified DESI file-availability snapshot.
2. Download only files containing at least one mapped target.
3. Match `RVTAB.TARGETID` exactly to the Data Lab mapping.
4. Attach Gaia DR3 `source_id` only through that TARGETID mapping.
5. Verify RVTAB/FIBERMAP/SCORES row alignment before extracting values.
6. Restore official exposure MJD and per-arm S/N fields before visit aggregation.
7. Preserve catalogue separation and match mode on every epoch row.

A second, explicitly labelled recovery path may use DESI reference identifiers or epoch-propagated coordinates for sources absent from the convenience crossmatch. Recovery rows must retain their matching method, separation, ambiguity margin, and catalogue epoch and may not be silently merged with exact-TARGETID evidence.

## Gate interpretation

- Zero rows from the official convenience crossmatch are a valid null result **for that crossmatch**, not proof that no cohort member was ever assigned a DESI fiber.
- A crossmatch row establishes a nearest positional association between Gaia DR3 and a DESI zpix target within 1.5 arcsec.
- Exact `RVTAB.TARGETID` extraction establishes that the mapped DESI target has an MWS single-exposure measurement in the selected file.
- Extracted epochs prove only that measurements exist.
- Independent orbit support still requires clean visits, phase coverage, and a fixed-Gaia-orbit comparison.
- No stage authorizes a compact-object classification by itself.

## Confidentiality

The query code and aggregate counts are public. Source-level overlap rows, TARGETIDs, epoch measurements, orbit scores, and dossiers remain in the encrypted evidence relay until a release decision is made.
