# WP5 — Roche-geometry consistency protocol

Frozen: 2026-07-22

## Purpose

A large single-lined mass function is not sufficient evidence for a dark compact companion. The published orbit, inferred primary mass, and inferred stellar radius must first describe a geometrically possible system.

For every mass-scored source with Gaia GSP-Phot radius percentiles, HOU-COMPACT calculates the primary Roche-lobe radius at periastron. The periastron choice is conservative for eccentric systems because that is where the available lobe is smallest.

## Calculation

The orbital semi-major axis follows Kepler's third law. The primary Roche-lobe fraction uses the Eggleton approximation with `q = M1/M2`. The instantaneous periastron Roche-lobe radius is

`R_L1,peri = a (1-e) f_Eggleton(M1/M2)`.

The audit samples:

- period and eccentricity from their published uncertainties;
- primary-mass q16/q50/q84 summaries;
- edge-on minimum-companion-mass q16/q50/q84 summaries;
- Gaia GSP-Phot primary-radius lower/median/upper summaries.

Mass and radius quantile products are approximated by positive split-normal draws. This is intentionally an audit rather than a joint evolutionary-orbital fit. The exact random seed is deterministic per Gaia source and solution ID.

## Statuses

- `geometry_inconsistent`: the lower filling-factor quantile exceeds unity or at least 95% of draws overflow the periastron Roche lobe;
- `near_or_overflowing_roche_lobe`: the median filling factor exceeds 0.8 or at least half the draws exceed 0.8;
- `detached_geometry_consistent`: neither contact condition is reached;
- `input_error`: required orbit, mass, or radius information is unavailable or unphysical.

## Triage behavior

`geometry_inconsistent`, missing, and failed audits are held before high-mass follow-up. Near-contact systems may remain in follow-up with an explicit caution because interacting binaries can be astrophysically real, but their single-star mass and radius interpretation is not trustworthy without dedicated modelling.

## Interpretation boundary

Roche inconsistency challenges the adopted Gaia orbit and/or single-star stellar parameters; it does not identify the correct alternative. Roche consistency is necessary but not sufficient for a detached dark-companion interpretation. Spectral multiplicity, composite SED, hierarchy, stripped-star, novelty, and independent-orbit gates remain mandatory.
