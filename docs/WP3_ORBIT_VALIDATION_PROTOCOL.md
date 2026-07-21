# WP3 — Independent Gaia/DESI orbit-validation protocol

Frozen: 2026-07-21

## Question

For a Gaia DR3 SB1-family solution with published period, phase, eccentricity, argument of periastron, and primary RV semi-amplitude, do the independent DESI single-epoch velocities follow the same fixed Keplerian shape?

## Model comparison

For each Gaia orbital solution, evaluate the Gaia-published velocity shape at every clean DESI epoch:

`v_shape(t) = K1 [cos(nu(t) + omega) + e cos(omega)]`

The eccentric anomaly is obtained from Kepler's equation. Gaia's relative periastron epoch is converted from `gaia_source.ref_epoch` to an absolute epoch before evaluating DESI MJDs. For circular `SB1C` solutions, null eccentricity and argument of periastron are normalized to Gaia's circular convention: `e=0`, `omega=0`, with the relative epoch corresponding to maximum RV.

Two equal-complexity models are compared:

1. constant velocity, with one fitted weighted mean;
2. fixed Gaia orbit shape plus one fitted additive DESI systemic-velocity offset.

Period, phase, eccentricity, argument of periastron, and K1 are not re-fitted in the first validation pass. Therefore a positive

`Delta chi2 = chi2_constant - chi2_fixed_orbit`

means the Gaia shape explains independent DESI variation better without receiving extra free shape parameters.

## Default data exclusions

- failed RVSpecFit rows;
- non-zero `RVS_WARN`;
- non-zero `FIBERSTATUS`;
- non-finite or non-positive RV uncertainties;
- RV uncertainty above 20 km/s;
- no arm with S/N at least 2;
- all backup-program rows until the published backup correction is separately implemented and validated.

These thresholds are pilot defaults, not a final selection function. Every sensitivity analysis must preserve the alternative thresholds and resulting table hashes.

## Output per Gaia solution

- raw and clean DESI epoch counts;
- excluded backup count;
- time baseline and circular phase coverage;
- constant-model chi-square and reduced chi-square;
- fixed-orbit chi-square and reduced chi-square;
- Delta chi-square;
- maximum pairwise RV significance;
- fitted additive DESI systemic velocity;
- DESI-minus-Gaia systemic-velocity difference when available;
- RMS orbit residual;
- explicit status or model error.

## Advancement gate

WP3 does not identify compact objects. A system may advance to mass inference only when:

- at least two clean non-backup DESI epochs exist;
- the fixed-orbit calculation succeeds with a traceable Gaia solution ID;
- epoch times provide non-zero phase coverage;
- the result is stable to a documented RV jitter floor and reasonable quality-threshold changes;
- duplicate exposures and survey-specific systematics have been audited.

A strong positive Delta chi-square confirms only that DESI supports Gaia's orbital shape. A poor fixed-orbit fit may indicate a bad Gaia solution, an incorrect crossmatch, a higher-order multiple, template/systematic problems, or genuine orbital evolution; it is not automatically a null result.
