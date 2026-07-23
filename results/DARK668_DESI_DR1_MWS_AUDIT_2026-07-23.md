# Dark-668 DESI DR1 MWS exact-identity coverage audit

**Frozen date:** 2026-07-23  
**Workflow run:** `30012302358`  
**Status:** complete, all pipeline gates green

## Scope

This candidate-safe receipt freezes an exact Gaia DR3 identity query of the 668 published massive dark-companion candidates against the public NOIRLab Astro Data Lab table `desi_dr1.mws`.

The table contract provides Gaia DR3 `source_id`, DESI `TARGETID`, HEALPix, survey/program and source-file locators, together with coadded RV and quality fields. Queries used exact Gaia DR3 integer constraints in 17 bounded batches. DESI `program = backup` was excluded because DR1 documents substantial radial-velocity systematics for backup targets. No positional association was used.

Source-level Gaia IDs, TARGETIDs, HEALPix values, filenames and coadded measurements were encrypted before artifact persistence. The public receipt exposes only aggregate counts and cryptographic digests.

## Frozen input contract

- RGB candidates: 389
- Main-sequence candidates: 279
- Combined exact candidate count: 668
- RGB catalogue MD5: `000dac405ed9e75d28f7c47d206ec345`
- Main-sequence catalogue MD5: `07eb6acff1f98d3a656741f2e61daed3`

## DESI DR1 MWS coverage result

- Submitted target count: 668
- Exact-ID TAP requests: 17
- Targets with an exact non-backup `desi_dr1.mws` match: 0
- Exact-identity coadded rows: 0
- Quality-pass coadded rows: 0
- Unique non-backup single-epoch RVTAB files required: 0
- Unmatched targets: 668

Every batch completed successfully with HTTP 200 and returned only the CSV header. Therefore this is a clean exact-identity coverage null, not an interrupted query or parser failure.

Because no candidate matched the non-backup DESI DR1 MWS table, no target-level single-epoch Healpix file download was scientifically necessary. The generic DESI RVTAB/FITS tooling remains available for future samples, but downloading public example or unrelated files cannot improve this 668-source audit.

## Interpretation

This result establishes that the current 668-source catalogue has no exact Gaia DR3 overlap with the non-backup rows exposed by `desi_dr1.mws` under the frozen query contract. It does not imply that the candidates lack DESI spectra outside this table, future DESI releases, excluded backup data, alternative reductions or other surveys.

The backup program remains excluded rather than used opportunistically because its documented RV systematics would weaken, not strengthen, a compact-companion audit.

## Reproducibility and privacy receipts

Candidate-safe artifact:

- Artifact ID: `8565626642`
- Artifact digest: `sha256:67effc06849d36650305fc27949760e2a6dc178be038cc2ad3b3e4d3debe8ea4`
- Retention: 30 days from the frozen run

Encrypted source-level artifact:

- Artifact ID: `8565626048`
- Artifact digest: `sha256:6c7e1be86113ef7cfbbc3666b139520d8cf9a09a87326006ddaabd5fa5a341fe`
- Retention: 90 days from the frozen run

The source-level archive was packed and encrypted with AES-256-CBC using PBKDF2 with 200,000 iterations. Its random passphrase was wrapped with RSA-OAEP-SHA256. Plaintext source-level products and temporary secrets were deleted after encryption.

## Claim boundary

This audit establishes exact public-input integrity, exact Gaia DR3 identity queries, a non-backup DESI DR1 MWS coverage null and the absence of any required candidate Healpix download. It is not a variability, orbit, binary, compact-object or novelty result.
