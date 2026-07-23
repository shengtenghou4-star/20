# Dark-668 protocol v0.1

## Frozen target

Audit the two public catalogues associated with Müller-Horn et al., *Dormant black hole candidates from Gaia DR3 summary diagnostics*, Zenodo record `19181131` (v2). Apply the authors' frozen promising-candidate cut exactly:

```text
fit_companion_mass > 3.0 and flag_quality == True
```

The expected aggregate is 389 RGB rows plus 279 main-sequence rows, for 668 public candidates.

## Claim boundary

A catalogue row is a follow-up target, not a confirmed compact object. No black-hole, neutron-star, binary, or novelty claim is authorized by the catalogue ingestion or ranking stage.

## Privacy and priority policy

- Generic ingestion, validation, and deterministic scoring code may be public.
- Source-level rankings, cross-survey matches, velocities, orbital fits, spectra, SED evidence, contamination notes, candidate cards, and novelty audits remain outside the public repository.
- Public CI may emit only checksums, row counts, schema checks, and aggregate score summaries.
- Any source-level artifact must be encrypted before leaving the private execution environment.

## First scientific gates

1. Reproduce the exact 389 + 279 selection from the frozen v2 files.
2. Rank all 668 for public-spectroscopy follow-up without classifying them.
3. Cross-match RGB targets first against release-aware LAMOST DR8 multi-epoch products.
4. Require authoritative identity, multiple independent visits, useful orbital phase coverage, and reproducible RV uncertainties.
5. Reject pulsation, luminous multiplicity, hierarchy, blend, stripped-star, and catalogue-artifact explanations before any compact-object language.
6. Preserve a negative result if no target has adequate public coverage.

## Initial priority score

The first queue combines posterior mass support, a conservative mass lower-bound proxy, brightness, parallax signal-to-noise, Gaia RV transit count, mass/period precision, and a modest RGB reliability prior. It is a scheduling heuristic only and must not enter the scientific likelihood as data.
