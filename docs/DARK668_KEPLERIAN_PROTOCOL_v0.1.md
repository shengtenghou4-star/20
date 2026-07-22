# Dark-668 full Keplerian RV protocol v0.1

Frozen: 2026-07-23

## Purpose

This work package is the second RV model gate after exact survey identity, per-spectrum uncertainty recovery, quality filtering, independent-visit aggregation, and period-prior circular-RV triage.

It asks:

> Among targets already showing period-compatible independent RV variability, does a full eccentric Keplerian model improve the fit enough to justify deeper physical and spectroscopic audit?

A successful fit is not a compact-object classification.

## Model

The single-lined radial velocity is

```text
v(t) = gamma + K [cos(nu(t) + omega) + e cos(omega)],
```

where the true anomaly `nu(t)` is obtained by solving Kepler's equation

```text
E - e sin(E) = M.
```

The fitted parameters are:

1. systemic velocity `gamma`;
2. logarithmic semi-amplitude `log K`;
3. eccentricity `e`;
4. argument of periastron `omega`;
5. mean anomaly at the first accepted visit `M0`;
6. logarithmic period `log P`.

The period is bounded by the same frozen asymmetric period-prior window used in the circular triage. No unpublished Gaia orbital phase or eccentricity is invented.

## Eligibility

Default requirements:

- exact external-survey source association;
- finite per-spectrum RV uncertainties and clean quality flags;
- closely spaced exposures aggregated into independent visits;
- at least seven independent visits;
- circular period-prior score with Delta BIC of at least 6 when a preselection table is supplied.

## Optimisation discipline

- deterministic multistart seeds are derived from the source identifier and frozen base seed;
- three fixed starts cover low, moderate, and high eccentricity regions;
- additional starts sample bounded period, eccentricity, phase, and amplitude space;
- every accepted solution must report finite parameters and successful least-squares termination;
- the best solution is selected by weighted chi-square;
- six free parameters are charged in the Keplerian BIC;
- the selected-period circular model remains charged four effective parameters;
- covariance is reported only when the local normal matrix is full rank and finite.

## Candidate-safe descriptive gates

Aggregate reports may count:

- Keplerian improvement over circular Delta BIC >= 2, 6, and 10;
- eccentricity bins below 0.2, from 0.2 to 0.5, and at least 0.5;
- reduced chi-square thresholds and covariance availability.

These thresholds rank follow-up effort. They do not establish a black hole, neutron star, or even a secure binary.

## Mandatory later gates

Any promoted target still requires:

- instrument zero-point and jitter sensitivity;
- posterior or profile-likelihood uncertainty mapping beyond local covariance;
- alias and window-function analysis;
- leave-one-visit-out and outlier robustness;
- spectral and SED luminous-companion tests;
- blend, hierarchy, pulsation, activity, and stripped-star rejection;
- independent primary-mass inference and physical geometry;
- catalogue and literature novelty audit;
- targeted spectroscopy filling missing orbital phases.

## Privacy

Source-level Keplerian parameters, velocities, ranks, and candidate cards are novelty-sensitive and must remain encrypted. Public artifacts may contain generic code, tests, hashes, aggregate attrition, and claim boundaries only.
