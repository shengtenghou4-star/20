# WP6 — candidate-safe triage sensitivity protocol

Frozen: 2026-07-22

## Purpose

The final HOU-COMPACT population result must not depend on one convenient threshold choice. The primary sensitivity experiment re-runs the complete sequential triage on the same immutable row-complete evidence table while varying four pre-specified gates.

## Frozen grid

- minimum clean DESI visits: 2 and 3;
- minimum orbital phase coverage: 0.10, 0.20, and 0.30;
- minimum `Delta chi-square` favoring the fixed Gaia orbit: 4, 9, and 16;
- maximum primary-mass fractional 68% width: 0.50, 0.75, and 1.00.

The Cartesian product contains 54 deterministic configurations. Every configuration receives a stable hash derived from its exact thresholds.

All other triage requirements remain fixed, including Gaia quality, absolute orbit-fit quality, mass-product status, high-risk contamination rejection, Roche geometry, and the descriptive q16 mass thresholds.

## Aggregate outputs

For each configuration the report contains only:

- cohort size;
- count at every first blocking stage;
- total count passing all current evidence gates;
- orbit-supported lower-mass, high-minimum-mass, and very-high-minimum-mass follow-up counts;
- aggregate SB1 versus SB1C counts;
- aggregate source-association-path counts when that field is available.

The summary JSON reports the minimum and maximum final counts across the full grid. It contains no source identifiers, row ranks, coordinates, TARGETIDs, or velocities.

## Interpretation

A stable result has a narrow outcome range across the grid. A wide range means conclusions depend strongly on coverage, phase, orbit-preference, or primary-mass-width thresholds and must be described as threshold-sensitive.

The sweep does not optimize thresholds and cannot be used to select the most favorable configuration. The nominal analysis remains the frozen 3-visit, 0.20 phase-coverage, 9-point Delta-chi-square, and 0.75 primary-width configuration.

## Reproducible command

```bash
python scripts/run_triage_sensitivity.py \
  outputs/followup_triage.csv \
  --output outputs/triage_sensitivity.csv \
  --summary-output outputs/triage_sensitivity.summary.json
```

Every output is linked to the row-complete triage input by SHA256. Any future expansion of the grid requires a new protocol version rather than silently modifying this one.
