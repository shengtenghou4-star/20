# WP5 — Spectral multiplicity evidence protocol

Frozen: 2026-07-22

## Purpose

A massive unseen companion claim is immediately weakened if the observed spectrum is better explained by two luminous line systems. This protocol compares one shifted stellar template with a two-shift mixture while preserving conservative language and explicit model penalties.

## Models

For a continuum-normalized spectrum, the one-component model fits:

- one discrete radial velocity;
- one non-negative line-depth amplitude;
- one unrestricted constant continuum offset.

The two-component model fits:

- two discrete radial velocities separated by a configured minimum;
- two non-negative line-depth amplitudes;
- one unrestricted constant continuum offset.

Both models use the same rest-frame template in the first pass. The two-component model is penalized with the Bayesian information criterion for its additional velocity and amplitude. Later production work must repeat the comparison over an explicit template library and atmospheric-parameter grid.

## Conservative evidence language

The permitted outputs are:

- `strong_two_component_spectral_evidence`;
- `weak_two_component_spectral_evidence`;
- `no_two_component_preference`.

Strong evidence requires both a substantial BIC improvement and a non-negligible secondary line amplitude. A failure to prefer the two-component model does not prove that the companion is dark: similar-temperature blends, low flux ratios, rapid rotation, poor wavelength coverage, low S/N, and template mismatch can hide a luminous secondary.

## Required audits

Before using this test in a candidate card:

- inspect the exact wavelength mask and inverse variance;
- repeat over multiple stellar templates;
- perturb continuum treatment and velocity-grid spacing;
- test known single-lined and double-lined controls;
- record velocity separation, amplitude ratio, chi-square, BIC, pixel count, and template identity;
- compare individual visits and coadded spectra;
- preserve all negative results and configuration hashes.

## Claim boundary

Two-component evidence is a luminous-companion warning. No two-component preference is only one passed contaminant check and cannot independently establish a compact object.
