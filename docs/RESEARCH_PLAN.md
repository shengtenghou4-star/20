# HOU-COMPACT Research Plan v0.1

Date frozen: 2026-07-21

## 1. Scientific objective

Construct and validate a ranked catalogue of Gaia DR3 systems for which an unseen compact companion remains a plausible explanation after independent DESI DR1 epoch-radial-velocity checks and aggressive contaminant rejection.

The project is successful at three possible levels:

1. **Catalogue result:** a reproducible Gaia–DESI crossmatch with calibrated rejection and ranking statistics.
2. **Population result:** a defensible statement about how many apparently massive dark-companion solutions survive independent spectroscopy and why the others fail.
3. **Discovery result:** one or more systems whose posterior and follow-up evidence strongly favour a black hole, neutron star, or massive white dwarf companion.

A null discovery result is scientifically useful if the selection function, rejection accounting, and upper limits are complete.

## 2. Starting population

The first pass uses Gaia DR3 `nss_two_body_orbit` entries with finite period and significance, joined to `gaia_source`. We retain all solution types initially and divide them into:

- astrometric orbit solutions;
- single-lined spectroscopic solutions (`SB1`, `SB1C`);
- combined astrometric–spectroscopic solutions (`AstroSpectroSB1`);
- control classes such as SB2 and eclipsing systems.

No hard black-hole mass threshold is applied before DESI crossmatching. Early mass cuts can create exactly the selection bias the project is meant to avoid.

## 3. DESI validation

DESI DR1 supplies both coadded and single-epoch RVSpecFit products. The single-epoch layer is the central independent test.

For every matched Gaia source we will record:

- number of usable DESI epochs;
- observation times and survey/program provenance;
- radial velocity and uncertainty;
- RVS warning flags and success state;
- signal-to-noise diagnostics;
- atmospheric parameters and fit quality;
- whether a known survey/program RV correction is required.

Initial variability statistics:

- weighted constant-RV chi-square;
- maximum pairwise RV significance;
- robust peak-to-peak velocity amplitude;
- posterior predictive residual under the Gaia orbit when enough orbital information is available.

The first two are triage statistics only. They cannot confirm a compact object.

## 4. Orbit consistency

For spectroscopic Gaia solutions, predict the primary RV at each DESI epoch from the Gaia period, eccentricity, periastron epoch, argument of periastron, systemic velocity, and semi-amplitude.

For astrometric-only solutions, fit the DESI velocities jointly with Gaia orbital information rather than pretending Gaia provides a complete RV curve.

Every likelihood must include:

- Gaia parameter covariance when available;
- DESI epoch uncertainty;
- a survey/program systematic term;
- phase uncertainty accumulated over the Gaia-to-DESI baseline;
- outlier or bad-epoch mixture probability.

## 5. Mass inference

For SB1-like systems, calculate the spectroscopic mass function

`f(M) = P K1^3 (1-e^2)^(3/2) / (2 pi G)`.

Infer the visible-star mass from stellar parameters and photometry with uncertainty. The companion posterior must marginalize over inclination unless the astrometric orbit constrains it.

Minimum companion mass is reported only as a lower bound. It is never treated as the posterior median.

## 6. Contaminant ladder

Candidates are downgraded or rejected through an explicit ladder:

1. bad astrometry or weak/correlated Gaia solution;
2. DESI reduction warning or low-S/N epoch;
3. survey-specific RV systematic;
4. mismatched Gaia/DESI source or blend;
5. SB2 or composite-spectrum evidence;
6. luminous companion consistent with photometry;
7. hierarchical triple explanation;
8. stripped star / unusual visible-star mass estimate;
9. orbital phase inconsistency;
10. prior identification in compact-object catalogues or literature.

Each rejection receives a machine-readable reason code. Negative results remain versioned.

## 7. Ranking output

The final rank is not a single opaque machine-learning score. It is a vector of auditable evidence:

- Gaia orbit reliability;
- DESI RV variability significance;
- Gaia-orbit/DESI consistency;
- probability companion mass exceeds WD/NS thresholds;
- probability of a luminous secondary;
- blend/triple risk;
- novelty status;
- follow-up value.

Candidate cards will show the raw measurements and every transformation used.

## 8. Scientific gates

### Gate A — Schema and provenance

Pass only when a small set of rows can be traced from official survey files to a normalized local table with checksums and column provenance.

### Gate B — Controls

Pass only when known constant-RV stars, known binaries, SB2 systems, and at least one published compact-object binary behave as expected.

### Gate C — Orbit prediction

Pass only when synthetic orbit recovery and published-object back-tests reproduce velocities within stated uncertainty.

### Gate D — Blind ranking

Only after Gates A–C may unidentified systems be ranked.

### Gate E — Discovery language

No object is described publicly as a compact-object detection without independent expert review and appropriate follow-up evidence.

## 9. Reproducibility

Every run receives:

- timestamped YAML/JSON manifest;
- Git commit SHA;
- input file URL and checksum;
- Gaia ADQL query text;
- software environment lock or package versions;
- row counts after every filter;
- deterministic random seed where applicable.

Raw multi-gigabyte survey products stay outside Git. Compact derived tables, manifests, and candidate cards are committed when licensing permits.

## 10. Immediate execution order

1. Run `queries/gaia_seed.adql` and preserve the result manifest.
2. Inspect the DESI single-epoch file schema on a small official file.
3. Build the Gaia-source-ID crossmatch.
4. Produce a 100–1000 object pilot containing controls and high-significance NSS systems.
5. Run RV quality-control statistics.
6. Implement Gaia-orbit phase prediction for SB1/SB1C.
7. Audit the first ranked tail before scaling.
