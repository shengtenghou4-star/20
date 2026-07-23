# Dark-668 exact Gaia-ID spectroscopy audit

**Frozen date:** 2026-07-23  
**Workflow run:** `30008562947`  
**Status:** complete, all pipeline gates green

## Scope

This receipt freezes a candidate-safe audit of the 668 published Gaia DR3 massive dark-companion candidates: 389 RGB systems and 279 main-sequence systems. The source-level identities, positions, spectra, radial velocities, rankings, orbit products and dynamical tables are not included here.

The public spectroscopy route used the anonymous LAMOST DR8 v2.0 browser search with its native Gaia DR3 source-ID list constraint. All 668 exact digit-string identifiers were submitted in one request with no coordinate cone, Gaia DR3-to-DR2 bridge, floating identifier, MEC expansion or approximate association. A returned row was retained only when its Gaia DR3 identifier exactly matched the submitted set.

## Frozen input contract

- RGB catalogue rows: 21,028
- RGB selected candidates: 389
- RGB catalogue MD5: `000dac405ed9e75d28f7c47d206ec345`
- Main-sequence catalogue rows: 19,664
- Main-sequence selected candidates: 279
- Main-sequence catalogue MD5: `07eb6acff1f98d3a656741f2e61daed3`
- Combined exact candidate count: 668
- Candidates whose catalogue mass-lower-bound proxy remains at least 3 solar masses: 145

## Exact LAMOST coverage

- Submitted target count: 668
- Anonymous exact-ID requests: 1
- Targets with at least one exact LAMOST match: 105
- Targets without an exact LAMOST match: 563
- Exact-identity spectrum rows: 183
- Spectrum rows passing the frozen measurement-quality gate: 100

Raw exact-identity epoch counts:

- At least 2 epochs: 43 targets
- At least 3 epochs: 18 targets
- At least 5 epochs: 2 targets
- At least 7 epochs: 1 target
- At least 10 epochs: 1 target

Quality-pass epoch counts:

- At least 2 epochs: 21 targets
- At least 3 epochs: 5 targets
- At least 5 epochs: 1 target
- At least 7 epochs: 0 targets
- At least 10 epochs: 0 targets

After cadence summarization:

- At least 2 usable epochs: 41 targets
- At least 3 usable epochs: 13 targets
- At least 5 usable epochs: 2 targets
- At least 10 usable epochs: 1 target
- Coverage-summarized targets: 41
- Single-usable-epoch targets: 60
- No-usable-epoch targets: 567
- Covered population counts: 40 main-sequence and 61 RGB targets

Descriptive raw-spread counts, before orbit claims:

- Raw RV amplitude at least 10 km/s: 18 targets
- Raw RV amplitude at least 20 km/s: 11 targets
- Raw RV amplitude at least 50 km/s: 3 targets
- Phase-coverage proxy at least 0.2: 29 targets
- Phase-coverage proxy at least 0.4: 11 targets
- Phase-coverage proxy at least 0.6: 0 targets

These raw-spread counts are prioritization diagnostics only. They are not evidence of orbital coherence and are not compact-object classifications.

## Frozen orbit and physical-audit outcome

The period-prior stage required at least 5 independent visits after the frozen two-hour visit aggregation and quality gates.

- Period-prior rows assessed: 668
- Targets reaching the period-prior scoring gate: 0
- Status: 668 insufficient independent visits

Consequently:

- Full Keplerian rows assessed: 668
- Full Keplerian fits performed: 0
- Status: 668 not preselected
- Dynamical/geometry rows assessed: 668
- Dynamical mass-function audits performed: 0
- Status: 668 not Keplerian-scored
- Point follow-up gates passed: 0
- Strong follow-up gates passed: 0

This is a **cadence-limited null result for LAMOST DR8 under the frozen gates**. It does not show that the 668 catalogue candidates are false, nor that they lack compact companions. It shows that LAMOST DR8 alone does not provide enough independent, quality-controlled visits to validate an orbit for any of the 668 systems under this protocol.

## Reproducibility and privacy receipts

Candidate-safe artifact:

- Artifact ID: `8564108921`
- Artifact digest: `sha256:ba78711445c0f30c44b09839cd4a4e0876e588b4f49d1f778b5936e9fbae8643`
- Retention: 30 days from the frozen run

Encrypted source-level artifact:

- Artifact ID: `8564108459`
- Artifact digest: `sha256:ccd19dc484a404ae86cbf94e5816eed50b1108468cb92a813712ca246cbada8b`
- Retention: 90 days from the frozen run

The source-level archive was packed and encrypted with AES-256-CBC using PBKDF2 with 200,000 iterations. Its random passphrase was wrapped with RSA-OAEP-SHA256. Plaintext source-level files and temporary secrets were deleted after encryption.

## Claim boundary

This audit establishes exact public-input integrity, exact Gaia DR3-to-LAMOST identity matching, aggregate spectroscopic coverage, cadence limitations and complete zero-result propagation through period, Keplerian and dynamical stages. It does not classify any source as a binary, black hole, neutron star or other compact object, and it does not establish novelty. Independent spectroscopy, instrument-offset controls, stellar-parameter validation, contamination audits, blend/triple/activity rejection and literature review remain necessary.
