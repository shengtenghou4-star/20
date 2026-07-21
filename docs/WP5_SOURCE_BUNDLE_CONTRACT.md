# WP5 — Private spectral and SED bundle contract

Frozen: 2026-07-22

## Purpose

The source-level scoring commands consume compact private NPZ bundles rather than embedding candidate-sensitive arrays in the public repository. Every output records the input bundle hash, array shapes, settings, and an interpretation boundary.

## Spectral bundle

`score_spectral_multiplicity.py` requires:

- `wavelength`: strictly increasing observed wavelength array;
- `flux`: continuum-normalized observed flux;
- `inverse_variance`: positive weights on usable pixels;
- `template_wavelength`: strictly increasing rest-frame template wavelength;
- `template_flux`: continuum-normalized rest-frame template flux;
- `velocity_grid_kms`: strictly increasing trial radial velocities.

Example:

```bash
python scripts/score_spectral_multiplicity.py \
  private/HOUC-EXAMPLE-spectrum.npz \
  --source-id '<private-source-id>' \
  --solution-id '<private-solution-id>' \
  --output private/spectral_evidence.csv
```

The result records the best one-velocity and two-velocity fits, BIC difference, velocity separation, secondary-to-primary line amplitude, and the conservative evidence status.

The current executable pilot uses one supplied stellar template shifted to one or two velocities. Production analysis must vary template type, wavelength region, continuum treatment, masks, calibration assumptions, and velocity-grid resolution.

## SED bundle

`score_sed_multiplicity.py` requires:

- `flux`: observed broad-band flux vector;
- `flux_error`: positive one-sigma uncertainties;
- `template_fluxes`: array with shape `(n_templates, n_bands)`.

Optional arrays are:

- `template_labels`: one label per template;
- `band_names`: one label per photometric band.

Example:

```bash
python scripts/score_sed_multiplicity.py \
  private/HOUC-EXAMPLE-sed.npz \
  --source-id '<private-source-id>' \
  --solution-id '<private-solution-id>' \
  --output private/sed_evidence.csv
```

The result records the best single-template and two-template mixture, BIC difference, secondary flux fraction, and evidence status.

Production analysis must record extinction treatment, parallax/distance handling, zero points, variability, upper limits, model grid, and photometric covariance. The compact command does not infer those choices.

## Privacy and reproducibility

NPZ bundles and source-level outputs belong in the private evidence vault. Public code may include synthetic fixtures only. Candidate identifiers, observed arrays, and source-level evidence must not be copied into public CI logs or issues.
