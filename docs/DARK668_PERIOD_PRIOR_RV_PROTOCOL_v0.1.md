# Dark-668 period-prior RV protocol v0.1

Frozen: 2026-07-23

## Why this analysis is separate from fixed Gaia-orbit validation

The Dark-668 catalogues were inferred from Gaia DR3 summary diagnostics. They provide posterior summaries for orbital period, companion mass, and inclination, but not a complete published orbital phase/eccentricity solution for each target. Therefore the existing HOU-COMPACT fixed-orbit comparison must not be applied to these rows as though a Gaia velocity curve were known.

This work package asks a narrower question:

> Do independent multi-visit radial velocities show temporally coherent variation at a period compatible with the published period posterior?

A positive result promotes a target for full orbital modelling and follow-up. It is not a black-hole confirmation.

## Input requirements

A source is scoreable only after:

1. exact Gaia DR3 → Gaia DR2 identity bridging;
2. exact association with an external spectroscopic catalogue;
3. per-spectrum radial velocities with finite positive uncertainties;
4. conservative quality flags and signal-to-noise cuts;
5. aggregation of closely spaced exposures into independent visits;
6. at least five independent visits by default.

The LAMOST multiple-epoch summary table alone is insufficient for scientific scoring because it does not provide the per-spectrum RV uncertainties required by the likelihood.

## Frozen first-pass model

For each candidate, construct a deterministic period grid from the published asymmetric period summary. The default grid spans the central value ±3 reported error scales, with a factor-of-two fallback when uncertainty fields are absent.

At every trial period, fit the weighted circular model

```text
v(t) = gamma + A sin(2 pi t / P) + B cos(2 pi t / P).
```

Compare it against a constant-velocity model. The periodic model is charged four effective BIC parameters: systemic velocity, sine coefficient, cosine coefficient, and the selected period. Positive `delta_bic_constant_minus_periodic` favors coherent period-compatible variability.

This circular model is a triage proxy. It is not a full Keplerian orbit and can miss eccentric systems.

## Look-elsewhere and pseudo-replication controls

- Exposures within the configured visit window are combined by inverse variance.
- Visit uncertainties are inflated when same-visit exposures disagree more than expected.
- A deterministic within-source permutation test shuffles velocity/error pairs among observation times and repeats the full period-grid scan.
- The empirical false-alarm probability uses the add-one correction.
- Source-level null scores and candidate rankings remain private.

## Candidate-safe descriptive thresholds

Aggregate reports may count rows at:

- Delta BIC ≥ 6, 10, and 20;
- permutation false-alarm probability ≤ 0.10, 0.05, and 0.01;
- joint gates Delta BIC ≥ 10 with FAP ≤ 0.05, and Delta BIC ≥ 20 with FAP ≤ 0.01.

These are follow-up prioritization thresholds, not discovery or classification thresholds.

## Mandatory downstream gates

A promoted target still requires:

- full Keplerian inference with uncertainty propagation;
- independent instrument zero-point treatment;
- spectral and SED tests for a luminous companion;
- blend, hierarchy, pulsation, activity, and stripped-star rejection;
- primary-star mass re-evaluation;
- Roche geometry and physical consistency;
- catalogue/literature novelty audit;
- preferably new targeted spectroscopy covering missing orbital phases.

## Claim boundary

No output from this work package may call a source a binary, neutron star, black hole, or compact object. The strongest permitted state is `period_prior_rv_followup`, meaning only that independent RV data merit deeper analysis.
