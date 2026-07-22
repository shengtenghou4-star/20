# WP2 exact Gaia–DESI overlap protocol

Frozen: 2026-07-22

## Problem corrected

A DESI per-HEALPix RV file being present in the same NSIDE=64 cell as a Gaia source does **not** establish that the source received a DESI fiber. Positional matching every Gaia seed against every row in an available cell is useful as a diagnostic, but it is not the authoritative source-to-spectrum relationship.

The primary production path therefore uses NOIRLab Astro Data Lab's official 1.5-arcsec nearest-neighbour convenience crossmatch between Gaia DR3 and `desi_dr1.zpix`, then joins the crossmatch's DESI-side identifier to `desi_dr1.zpix.id` to recover `TARGETID`, survey, program, and HEALPix. Exact `TARGETID` equality is authoritative once this mapping exists; membership in the precomputed positional crossmatch is not guaranteed complete for high-proper-motion, blended, crowded, or otherwise difficult sources.

The independent recovery path uses a different identifier chain. DESI DR1 documents `FIBERMAP.REF_CAT='G2'` and `REF_ID` as Gaia DR2 source identifiers. Gaia explicitly warns that source IDs must not be assumed stable between DR2 and DR3. HOU-COMPACT therefore queries `gaiadr3.dr2_neighbourhood`, audits nearest-neighbour ambiguity, and only then requires exact DESI `REF_ID` equality.

Official references:

- https://datalab.noirlab.edu/data/desi
- https://datalab.noirlab.edu/docs/manual/UsingAstroDataLab/ServiceInterfaces/QueryManager/QueryManager.html
- https://datalab.noirlab.edu/help/index.php?qa=1248
- https://datalab.noirlab.edu/help/index.php?qa=1595
- https://datalab.noirlab.edu/help/index.php?qa=2099
- https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_cross-matches/ssec_dm_dr2_neighbourhood.html
- https://data.desi.lbl.gov/doc/access/database/

## Data Lab TARGETID contract

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

## Gaia DR2 REF_ID recovery contract

For bounded Gaia DR3 source-ID batches:

```sql
SELECT
    d.dr3_source_id,
    d.dr2_source_id,
    d.angular_distance,
    d.magnitude_difference,
    d.proper_motion_propagation
FROM gaiadr3.dr2_neighbourhood AS d
WHERE d.dr3_source_id IN (...)
ORDER BY d.dr3_source_id, d.angular_distance,
         ABS(d.magnitude_difference), d.dr2_source_id
```

All neighbourhood rows are retained. The audited one-row bridge accepts the nearest DR2 counterpart only when it lies within 1000 mas and is either unique or separated from the second-nearest neighbour by at least 5 mas. These are frozen pilot gates, not universal identity criteria. Ambiguous and distant bridges remain recorded but are not used for extraction.

A recovered DESI row must satisfy all of the following:

1. an accepted DR3-to-DR2 neighbourhood bridge;
2. `FIBERMAP.REF_CAT='G2'`;
3. exact integer equality between `FIBERMAP.REF_ID` and the accepted DR2 source ID;
4. RVTAB/FIBERMAP/SCORES row alignment.

The output preserves the DR2–DR3 angular distance, neighbour count, distance margin, and explicit match mode.

## Exact epoch extraction

1. Intersect mapped files with the immutable verified DESI file-availability snapshot.
2. Download only files containing at least one relevant Gaia source or mapped target.
3. Prefer exact `RVTAB.TARGETID` equality from the Data Lab mapping.
4. Independently attempt accepted DR2-neighbourhood plus exact `G2/REF_ID` equality.
5. Verify RVTAB/FIBERMAP/SCORES row alignment before extracting values.
6. Restore official exposure MJD and per-arm S/N fields before visit aggregation.
7. Preserve catalogue separation, ambiguity information, and match mode on every epoch row.
8. De-duplicate rows reached through both exact paths and retain agreement/disagreement provenance.

Epoch-propagated coordinate matching remains a diagnostic fallback. It may not silently replace either identifier-based path.

## Gate interpretation

- Zero rows from the official convenience crossmatch are a valid null result **for that crossmatch**, not proof that no cohort member was ever assigned a DESI fiber.
- A crossmatch row establishes a nearest positional association between Gaia DR3 and a DESI zpix target within 1.5 arcsec.
- An accepted DR2 bridge plus exact `G2/REF_ID` establishes a release-aware identifier link to the DESI target metadata, subject to the recorded neighbourhood ambiguity gates.
- Exact `RVTAB.TARGETID` or accepted `G2/REF_ID` extraction establishes that the mapped target has an MWS single-exposure measurement in the selected file.
- Extracted epochs prove only that measurements exist.
- Independent orbit support still requires clean visits, phase coverage, and a fixed-Gaia-orbit comparison.
- No stage authorizes a compact-object classification by itself.

## Confidentiality

The query code and aggregate counts are public. Source-level overlap rows, release-identifier bridges, TARGETIDs, epoch measurements, orbit scores, and dossiers remain in the encrypted evidence relay until a release decision is made.
