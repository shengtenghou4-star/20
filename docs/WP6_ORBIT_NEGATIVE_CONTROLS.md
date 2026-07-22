# WP6 — fixed-orbit negative-control protocol

Frozen: 2026-07-22

## Purpose

A positive fixed-Gaia-orbit score is meaningful only when it exceeds chance phase alignment and when the fitted cross-survey velocity zero point behaves exactly as intended. HOU-COMPACT therefore runs two deterministic controls on the same Gaia cohort, DESI measurements, quality cuts, and visit aggregation used by the nominal analysis.

## Phase-scramble control

For every Gaia orbital solution and every control repetition, the relative periastron epoch is shifted by a deterministic uniform random fraction of one full orbital period. Period, eccentricity, argument of periastron, primary RV semi-amplitude, DESI cadence, velocities, uncertainties, and visit structure remain unchanged.

This destroys only the published Gaia–DESI phase relation. Each scrambled realization is scored through the same constant-velocity versus fixed-orbit comparison as the nominal data.

The default ensemble contains 100 repetitions. Candidate-safe outputs report:

- scored and absolutely acceptable orbit counts;
- counts with `Delta chi-square` at least 4, 9, and 16;
- minimum, median, and maximum null counts;
- empirical upper-tail probabilities using the add-one correction.

The control is not used to select a favorable threshold. Thresholds remain frozen before the result is inspected.

## Systemic-offset invariance

The first-pass orbit model fits one additive DESI systemic-velocity offset per source. Consequently, adding an arbitrary constant velocity to every DESI measurement of one source must not change:

- constant-model chi-square;
- fixed-orbit chi-square;
- `Delta chi-square`;
- fixed-orbit reduced chi-square.

The audit adds a deterministic Gaussian offset independently to every source and verifies the above statistics to a frozen numerical tolerance. Any failure indicates an implementation or data-alignment problem and blocks scientific interpretation.

## Candidate-safe contract

The public control table contains one aggregate row per phase-scramble repetition. It contains no Gaia source IDs, DESI TARGETIDs, coordinates, velocities, orbit ranks, or candidate-level values. Input and output SHA256 hashes are recorded. Any source-level nominal or scrambled score table remains inside the encrypted evidence relay.

## Interpretation

A nominal count substantially above the phase-scrambled distribution supports the claim that Gaia phases predict independent DESI velocities better than chance. It does not establish a dark companion, compact object, correct source association, or correct stellar model. All identity, absolute-fit, mass, contamination, Roche, multiplicity, and novelty gates remain mandatory.

A null or non-significant result is scientifically usable: it shows that the available DESI cadence does not distinguish the published Gaia phase relation from chance under the frozen experiment.

## Reproducible command

```bash
python scripts/run_orbit_negative_controls.py \
  outputs/gaia_seed.ecsv \
  outputs/desi_epochs.csv \
  --output outputs/orbit_phase_scramble_control.csv \
  --summary-output outputs/orbit_phase_scramble_control.summary.json \
  --repetitions 100
```
