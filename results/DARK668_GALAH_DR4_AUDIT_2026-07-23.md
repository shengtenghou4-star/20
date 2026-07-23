# Dark-668 GALAH DR4 exact-identity audit

**Frozen date:** 2026-07-23  
**Workflow run:** `30010112895`  
**Status:** complete, all pipeline gates green

## Scope

This candidate-safe receipt freezes an independent GALAH DR4 audit of the 668 published Gaia DR3 massive dark-companion candidates. Source-level identities, positions, radial velocities, target overlap records, rankings, period scores, orbit products, and dynamical tables are excluded.

The public spectroscopy route used the anonymous Data Central TAP service and the registered per-spectrum table `galah_dr4.mainspectable`. Queries used exact Gaia DR3 integer constraints in 17 bounded batches. A returned row was retained only when its exact Gaia DR3 identity belonged to the submitted batch. No positional association was used.

GALAH was analysed independently. Its RV values were not numerically merged with LAMOST because survey-specific velocity zero points and nuisance offsets have not yet been calibrated for this target set.

## Frozen input contract

- RGB candidates: 389
- Main-sequence candidates: 279
- Combined exact candidate count: 668
- RGB catalogue MD5: `000dac405ed9e75d28f7c47d206ec345`
- Main-sequence catalogue MD5: `07eb6acff1f98d3a656741f2e61daed3`

## Exact GALAH DR4 coverage

- Submitted target count: 668
- Exact-ID TAP requests: 17
- Targets with at least one exact GALAH match: 37
- Targets without an exact GALAH match: 631
- Exact-identity per-spectrum rows: 38
- Rows passing the frozen GALAH quality gate: 16

The frozen quality gate required finite MJD and RV, a finite positive quoted RV uncertainty, `flag_sp = 0`, `flag_red = 0`, and CCD3 signal-to-noise greater than 30.

Raw exact-identity epoch counts:

- At least 2 epochs: 1 target
- At least 3 epochs: 0 targets
- At least 5 epochs: 0 targets
- At least 7 epochs: 0 targets
- At least 10 epochs: 0 targets

Quality-pass epoch counts:

- At least 2 epochs: 0 targets
- At least 3 epochs: 0 targets
- At least 5 epochs: 0 targets
- At least 7 epochs: 0 targets
- At least 10 epochs: 0 targets

After cadence summarization:

- Coverage-summarized targets: 1
- Single-usable-epoch targets: 36
- No-usable-epoch targets: 631
- At least 2 usable epochs: 1 target
- At least 3 usable epochs: 0 targets
- At least 5 usable epochs: 0 targets
- Raw RV amplitude at least 10 km/s: 0 targets

## Frozen orbit and physical-audit outcome

The period-prior stage required at least five independent quality-controlled visits.

- Period-prior rows assessed: 668
- Targets reaching the period-prior scoring gate: 0
- Full Keplerian fits performed: 0
- Dynamical mass-function/geometry audits performed: 0
- Point follow-up gates passed: 0
- Strong follow-up gates passed: 0

This is a **cadence-limited GALAH DR4 null result under the frozen gates**. It does not show that the catalogue candidates are false or lack compact companions. It shows that GALAH DR4 alone does not provide enough repeated, quality-controlled spectra for orbital validation of any candidate under this protocol.

## Reproducibility and privacy receipts

Candidate-safe artifact:

- Artifact ID: `8564720740`
- Artifact digest: `sha256:b1fea6fed10056f8ad34d9f907e08712dc91712ce88bc56ff215a4cb0b78335e`
- Retention: 30 days from the frozen run

Encrypted source-level artifact:

- Artifact ID: `8564720400`
- Artifact digest: `sha256:8c81d128b2bf42c09a219c882f29ec4fedfe2f66b8f70016d7e5134835e53420`
- Retention: 90 days from the frozen run

The source-level archive was packed and encrypted with AES-256-CBC using PBKDF2 with 200,000 iterations. Its random passphrase was wrapped with RSA-OAEP-SHA256. Plaintext source-level products and temporary secrets were deleted after encryption.

## Claim boundary

This audit establishes exact Gaia DR3-to-GALAH identity matching, aggregate per-spectrum coverage, strict quality-pass counts, cadence limitations, and complete zero-result propagation through period, Keplerian, and dynamical stages. It does not classify any source as a binary, black hole, neutron star, or other compact object, and it does not establish novelty. Cross-survey RV combination requires explicit instrument zero-point and nuisance-offset controls before scientific use.
