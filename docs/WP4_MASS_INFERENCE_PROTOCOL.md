# WP4 — Companion-mass inference protocol

Frozen: 2026-07-22

## Scientific products

WP4 produces two deliberately separate quantities for each validated SB1/SB1C orbit.

### 1. Edge-on minimum-mass distribution

For every Monte Carlo draw,

`f(M) = P K1^3 (1-e^2)^(3/2) / (2 pi G)`

and the positive root of

`f(M) = M2^3 sin(i)^3 / (M1 + M2)^2`

is solved with `sin(i)=1`. This is the robust spectroscopic lower bound after propagating the adopted uncertainties in period, K1, eccentricity, and primary mass.

The principal ranking statistic is the lower 16th percentile of this minimum-mass distribution, not the nominal mass and not a tail-sensitive mean.

### 2. Isotropic-inclination sensitivity distribution

A second product draws `cos(i)` uniformly, as required for randomly oriented orbital planes. This product shows how unknown inclination could increase M2. It is explicitly not a population posterior because the Gaia SB1 discovery and publication process is inclination-, amplitude-, period-, magnitude-, and quality-dependent.

The isotropic product may guide follow-up prioritization. It cannot establish a compact object.

## Primary-star mass

The current executable pilot can derive a provisional M1 distribution from Gaia GSP-Phot surface gravity and radius:

`M1/Msun = 10^(logg-logg_sun) (R/Rsun)^2`.

GSP-Phot states that these parameters assume a single star. The resulting M1 product is therefore triage-only. It may be biased by unresolved light, extinction, evolutionary-state degeneracy, and the same companion we are trying to detect.

Before a candidate claim, M1 must be re-estimated with independent stellar characterization, preferably using DESI atmospheric parameters plus an explicit isochrone or stellar-evolution model, with photometric/SED consistency checks.

## Current covariance status

The v4 Gaia query preserves `corr_vec`, `bit_index`, and all reported one-dimensional errors. The first executable Monte Carlo uses a diagonal orbital-error approximation. This approximation is frozen and labelled in every output manifest.

No final uncertainty claim is allowed until the Gaia SB1/SB1C correlation-vector mapping is independently implemented, tested against the official data model, and compared with the diagonal result.

## Quantities retained

For both mass products, preserve:

- 1st, 5th, 16th, 50th, 84th, 95th, and 99th percentiles;
- probabilities of M2 exceeding fixed numeric thresholds;
- random seed and draw count;
- exact input values and input-file checksums;
- the inclination prior and any minimum-inclination conditioning;
- the primary-mass method and uncertainty width;
- the orbital covariance mode.

Numeric thresholds are follow-up gates, not object classifications. In particular, crossing 1.4, 2.5, 3, or 5 solar masses does not by itself distinguish a compact remnant from a luminous star, blend, hierarchy, stripped star, bad orbit, or bad primary-mass estimate.

## Advancement gate to contaminant rejection

A system advances from WP4 only when:

- independent DESI epochs support the fixed Gaia orbit shape;
- at least three clean, non-backup epochs are available for priority status;
- phase coverage and time baseline are documented;
- the minimum-mass result is stable to reasonable RV jitter and quality cuts;
- the primary-mass prior is finite and not pathologically broad;
- Gaia quality flags and period confidence are retained and audited;
- the diagonal-versus-correlated orbital-uncertainty sensitivity is eventually quantified.

WP5 must then search for a luminous secondary, blends, triples, stripped stars, catalogue duplicates, known binaries, and literature precedence before any compact-object language is used.
