# Dark-668 dynamical mass and geometry audit protocol v0.1

Frozen: 2026-07-23

## Purpose

This work package begins only after a target has passed exact survey identity,
per-spectrum radial-velocity uncertainty recovery, quality filtering, independent-
visit construction, period-prior coherence triage, and a full Keplerian fit.

It asks three narrower questions:

1. What single-lined spectroscopic mass function follows from the fitted period,
   semi-amplitude, and eccentricity?
2. Given the catalogue primary-mass estimate, what is the edge-on minimum companion
   mass, and is its local-error lower bound still astrophysically interesting?
3. Does the fitted orbit produce a physically strained periastron/Roche geometry for
   the visible star?

None of these calculations alone classifies a compact object.

## Mass function

The fitted orbit is converted to

```text
f(M) = P K^3 (1 - e^2)^(3/2) / (2 pi G)
     = M2^3 sin^3(i) / (M1 + M2)^2.
```

Setting `sin(i)=1` gives the minimum companion mass. The implementation solves the
monotonic mass-function equation numerically and fails closed for non-finite or
non-physical inputs.

## Local uncertainty bracket

When local Kepler covariance errors are available, a deterministic one-sigma envelope
is formed using the monotonic directions of `P`, `K`, and `e`:

- lower mass function: lower `P`, lower `K`, higher `e`;
- upper mass function: higher `P`, higher `K`, lower `e`.

The corresponding minimum-mass envelope is then solved at the frozen primary mass.
This is a local diagnostic, not a posterior. A strong follow-up gate requires the
minimum-mass lower envelope, not merely the central value, to exceed the configured
threshold.

## Catalogue consistency

The RV-derived minimum mass is compared with the published summary-diagnostic
companion-mass interval. Because the RV value is an edge-on minimum, lying below the
published interval is normally compatible with an unknown inclination. A minimum-mass
lower bound above the published upper interval is instead flagged for audit: it may
indicate a wrong association, an RV zero-point problem, an alias, underestimated
uncertainty, or tension in the summary-diagnostic inference.

## Geometry proxy

The relative semimajor axis is calculated from Kepler's third law using the primary
mass and edge-on minimum companion mass. The periastron separation is multiplied by
the Eggleton primary Roche-lobe fraction, and the visible-star radius is divided by
that Roche-lobe radius.

This is explicitly a proxy. The true inclination and companion mass are unknown, so it
is not a universal conservative exclusion. It is used to expose contact-like or
physically strained solutions before expensive follow-up.

## Frozen descriptive gates

Default point-follow-up requirements are:

- Keplerian improvement over the selected-period circular model: Delta BIC at least 6;
- Keplerian reduced chi-square no greater than 5;
- edge-on minimum companion mass at least 3 solar masses;
- primary Roche-fill proxy no greater than 0.8.

The strong-follow-up gate replaces the point minimum-mass requirement with the local
minimum-mass lower envelope of at least 3 solar masses.

These thresholds rank audit effort. They do not establish a black hole, neutron star,
or secure binary.

## Mandatory later gates

A promoted target still requires:

- instrument and survey zero-point sensitivity;
- jitter and error-floor sensitivity;
- alias/window-function and leave-one-visit-out tests;
- posterior or profile-likelihood orbit uncertainty;
- independent primary-mass and radius inference;
- SED, spectral-disentangling, blend, hierarchy, activity, pulsation, and stripped-star
  rejection;
- astrometric-orbit/photocentre consistency when available;
- literature and catalogue novelty audit;
- targeted spectroscopy at missing orbital phases.

## Privacy

Source identifiers, fitted parameters, masses, geometry values, ranks, and target cards
remain encrypted. Public products may contain generic code, tests, hashes, aggregate
attrition counts, and claim boundaries only.
