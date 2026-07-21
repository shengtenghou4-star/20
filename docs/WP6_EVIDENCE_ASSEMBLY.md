# WP6 — Final evidence assembly contract

Frozen: 2026-07-22

## Purpose

The final source-level table combines independent evidence products without silently duplicating rows, overwriting fields, or inventing missing results. It then applies the frozen claim-readiness policy.

## Merge rules

- The base table and every evidence table must contain unique `(source_id, solution_id)` keys.
- Every merge is validated as one-to-one.
- Overlapping non-key columns are rejected. Evidence provenance must be resolved before merging rather than hidden behind automatic suffixes.
- The base source set is preserved with left joins.
- Each table adds a Boolean `<name>_row_present` field.
- Missing evidence remains missing and becomes a claim-readiness blocker; it is never converted to a clean result.

## Expected evidence families

A production assembly normally includes named tables for:

- spectral multiplicity;
- composite SED evidence;
- independent primary-star characterization;
- hierarchy and stripped-star alternatives;
- catalogue and literature novelty.

The base table should already contain Gaia quality, independent DESI-visit orbit support, correlated mass inference, and Gaia-side contamination evidence.

## Reproducible command

```bash
python scripts/build_claim_evidence.py \
  outputs/followup_triage.csv \
  --evidence spectral=private/spectral_evidence.csv \
  --evidence sed=private/sed_evidence.csv \
  --evidence primary=private/independent_primary.csv \
  --evidence alternatives=private/alternative_hypotheses.csv \
  --evidence novelty=private/novelty_audit.csv \
  --output private/merged_claim_evidence.csv
```

The output manifest preserves every input path, hash and row count, per-table base-row coverage, final status counts, and the invariant that `claim_authorized_count` must remain zero.
