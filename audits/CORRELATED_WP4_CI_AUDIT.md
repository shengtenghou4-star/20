# Correlated WP4 CI audit trigger

Created: 2026-07-22

This branch triggers pull-request CI for the latest HOU-COMPACT implementation, including:

- Gaia SB1/SB1C `corr_vec` decoding;
- correlation-to-covariance construction for period, K1, and eccentricity;
- positive-semidefinite covariance repair with preserved variances;
- bounded physical multivariate draws;
- correlation-aware minimum-mass and isotropic-sensitivity products;
- transparent evidence-gated follow-up staging;
- all earlier Gaia, DESI, FITS-alignment, orbit, and primary-mass tests.

A passing CI run validates the synthetic software contract only. It does not validate the live Gaia archive schema, any real DESI overlap, or any astrophysical candidate.
