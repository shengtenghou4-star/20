# WP5 — Composite SED evidence protocol

Frozen: 2026-07-22

## Purpose

A second luminous star can reveal itself through broad-band flux ratios even when its spectral lines are weak or blended. This protocol compares one scaled stellar SED template with a two-template non-negative mixture.

## Model comparison

The single-star model selects one template and fits one non-negative scale. The composite model selects two distinct templates and fits two non-negative scales. Fits are weighted by reported flux errors and compared with BIC using the number of fitted continuous scales.

The template identity, atmosphere grid, extinction law, parallax treatment, zero points, bandpasses, and any photometric error floor remain explicit external inputs. Production work must audit them rather than treating a template-library result as model independent.

## Conservative evidence language

Permitted statuses are:

- `strong_composite_sed_evidence`;
- `weak_composite_sed_evidence`;
- `no_composite_sed_preference`.

Strong evidence requires both a substantial BIC improvement and a non-negligible secondary scale. A single-star preference does not establish a dark companion: a faint secondary, similar-temperature pair, extinction/model mismatch, variability, unresolved contamination, and sparse band coverage can conceal composite light.

## Production requirements

- convert every magnitude to flux with traceable zero points;
- propagate measurement and calibration uncertainties;
- include parallax and extinction consistently;
- fit a documented stellar-model grid;
- compare multiple extinction laws and photometric error floors;
- validate on known single and composite systems;
- preserve all band masks, template labels, coefficients, chi-square, BIC, and configuration hashes;
- combine this evidence with spectra, images, Gaia diagnostics, and hierarchy tests.

## Claim boundary

Composite SED evidence is a luminous-companion warning. No composite preference is only one passed contaminant check and cannot independently establish a compact object.
