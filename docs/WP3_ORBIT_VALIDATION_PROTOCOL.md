# WP3 — Independent Gaia/DESI orbit-validation protocol

Frozen: 2026-07-21; independent-visit amendment: 2026-07-22

## Question

For a Gaia DR3 SB1-family solution with published period, phase, eccentricity, argument of periastron, and primary RV semi-amplitude, do independent DESI radial-velocity visits follow the same fixed Keplerian shape?

## Independent-visit construction

Raw DESI exposures are not automatically independent orbital phase measurements. After the exposure-level quality cuts, temporally adjacent spectra are grouped by source into visits. A new visit begins when the observing night changes or the gap from the previous exposure exceeds two hours by default.

Within each visit:

- MJD and RV are inverse-variance weighted;
- the formal mean error is `sqrt(1/sum(w))`;
- if repeated exposures scatter more than expected, the error is inflated by `sqrt(max(1, chi2/(n-1)))`;
- any configured visit-level systematic floor is added in quadrature;
- exposure count, visit span, internal chi-square, and inflation factor are preserved.

All scientific gates count independent visits, not raw exposures. Treating each exposure as independent is allowed only as a labelled sensitivity analysis.

## Model comparison

For each Gaia orbital solution, evaluate the Gaia-published velocity shape at every independent DESI visit:

`v_shape(t) = K1 [cos(nu(t) + omega) + e cos(omega)]`

The eccentric anomaly is obtained from a monotonic bracketed solution of Kepler's equation, avoiding high-eccentricity Newton failures. Gaia's relative periastron epoch is converted from `gaia_source.ref_epoch` to an absolute epoch before evaluating DESI MJDs. For circular `SB1C` solutions, null eccentricity and argument of periastron are normalized to Gaia's circular convention: `e=0`, `omega=0`, with the relative epoch corresponding to maximum RV.

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

- raw exposure count, clean exposure count, and independent visit count;
- maximum exposures per visit, visit span, and internal error inflation;
- excluded backup count;
- time baseline and circular phase coverage;
- constant-model chi-square and reduced chi-square;
- fixed-orbit chi-square and reduced chi-square;
- Delta chi-square;
- maximum pairwise visit-RV significance;
- fitted additive DESI systemic velocity;
- DESI-minus-Gaia systemic-velocity difference when available;
- RMS orbit residual;
- explicit status or model error.

## Advancement gate

WP3 does not identify compact objects. A system may advance to mass inference only when:

- at least two clean non-backup independent DESI visits exist;
- priority status requires at least three independent visits;
- the fixed-orbit calculation succeeds with a traceable Gaia solution ID;
- visit times provide non-zero phase coverage;
- the result is stable to documented visit grouping, RV jitter, error-floor, and quality-threshold changes;
- duplicate exposures and survey-specific systematics have been audited.

A strong positive Delta chi-square confirms only that DESI supports Gaia's orbital shape. A poor fixed-orbit fit may indicate a bad Gaia solution, an incorrect crossmatch, a higher-order multiple, template/systematic problems, or genuine orbital evolution; it is not automatically a null result.
