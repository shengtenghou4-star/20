# Dark-668 frozen catalogue contract — 2026-07-23

## Live result

GitHub Actions run `29937514122` fetched the two public Zenodo v2 catalogues, verified the pinned checksums, parsed the complete tables, and reproduced the frozen promising-candidate cut.

| Population | Catalogue rows | Promising rows | Published MD5 | Downloaded bytes |
|---|---:|---:|---|---:|
| RGB | 21,028 | 389 | `000dac405ed9e75d28f7c47d206ec345` | 9,952,764 |
| Main sequence | 19,664 | 279 | `07eb6acff1f98d3a656741f2e61daed3` | 9,056,535 |
| **Total promising** |  | **668** |  |  |

Both catalogues contained unique source identifiers within their own table. The candidate-safe workflow artifact had digest:

```text
sha256:3a336017e55a7bf807df4bd2c2eb05cb3782e41f12b059692e85aff6ecefd691
```

## Frozen cut

```text
fit_companion_mass > 3.0 and flag_quality == True
```

## Interpretation boundary

This receipt proves input identity, schema compatibility, checksum agreement, and exact aggregate selection counts. It does not establish that any row is a binary, compact object, neutron star, or black hole. Source-level rankings and follow-up products remain outside public artifacts.
