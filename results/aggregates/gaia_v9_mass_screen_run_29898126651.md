# Gaia v9 minimum-companion-mass screen — encrypted relay run 29898126651

Frozen: 2026-07-22  
Status: candidate-safe aggregate; no source identifiers

## Result

The frozen Gaia v9 cohort contained 5,000 SB1-family orbital solutions. Primary-mass priors and correlated orbital Monte Carlo products were successfully produced for 2,283 systems. The remaining 2,717 rows lacked both usable Gaia FLAME mass percentiles and the complete GSP-Phot logg-radius inputs required by the frozen fallback; these are missing-information cases, not astrophysical rejections.

Among the 2,283 scored systems, the lower 16th percentile of the edge-on minimum companion-mass distribution had:

- median: 1.856 solar masses;
- 90th percentile: 3.160 solar masses;
- 95th percentile: 3.909 solar masses;
- 99th percentile: 7.092 solar masses;
- maximum: 20.551 solar masses.

Raw scored counts above conservative lower-bound thresholds were:

| Minimum-mass lower bound | All mass-scored | Gaia-quality gate passed | Gaia-quality passed and no strongest Gaia-side contamination flag |
|---|---:|---:|---:|
| q16 ≥ 1.4 solar masses | 1,770 | 1,644 | 1,290 |
| q16 ≥ 3 solar masses | 284 | 270 | 200 |
| q16 ≥ 5 solar masses | 57 | 52 | 43 |
| q16 ≥ 8 solar masses | 16 | 13 | 12 |

The 200 systems in the `q16 ≥ 3` / Gaia-quality-passed / no-strongest-Gaia-contamination subset had a median q16 minimum mass of 3.663 solar masses, median Gaia orbit significance of 40.16, and median 20 good Gaia RV epochs. This is a substantial **follow-up pool**, not a compact-object catalogue.

## What this establishes

The Gaia-only branch is no longer merely a software scaffold. It has produced a reproducible, uncertainty-propagated high-minimum-mass tail large enough to justify independent spectroscopic validation and aggressive contaminant rejection.

It does **not** establish that any member is a black hole, neutron star, white dwarf, or even a valid binary solution. A high inferred minimum mass can still be produced by an incorrect Gaia orbit, a poor single-star primary-mass model, blending, a luminous companion, a hierarchical triple, a stripped star, or other systematics.

## Current blocking gate

This relay extracted zero DESI single-epoch rows and therefore produced zero independent orbit scores. The previous file-selection method established only that DESI MWS RV files existed in the same NSIDE=64 cells. It did not establish that the individual Gaia source received a DESI fiber.

The production path has therefore been replaced by the official Gaia DR3 ↔ DESI DR1 zpix crossmatch followed by exact DESI `TARGETID` extraction. Until that path returns clean independent visits, every mass-screen object remains held before candidate interpretation.

## Provenance

- encrypted relay run: `29898126651`;
- public pipeline commit: `6259995a765eb6640eab925080fa43472eaaef50`;
- Gaia seed SHA256: `e3011c1a097d46d8ef04c1ae1e1b81f116c05392fc6c2d4ffa7470f23f3b005f`;
- primary-mass product SHA256: `db91334c9c9aa9827de7a402404fa17e3c33507ea8cb42016bbb3212a39cd144`;
- correlated-mass product SHA256: `a13031d1439a836c3f4e07f800164977b6d3d800b04fac1707c8b9ae5a9686ae`;
- machine-readable aggregate: `gaia_v9_mass_screen_run_29898126651.json`.

## Claim boundary

“Without strongest Gaia-side contamination flag” means only that the available Gaia audit did not emit `high_risk_blend_or_multiplicity_signal`. It is not equivalent to a clean system. Spectral multiplicity, composite SED, hierarchy, stripped-star, literature novelty, and independent orbit gates remain unresolved. No source identifiers, coordinates, TARGETIDs, or candidate-level rows are published here.
