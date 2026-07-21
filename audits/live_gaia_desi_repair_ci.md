# Live Gaia-DESI downstream repair CI audit

Created: 2026-07-22

Encrypted relay run `29856569461` returned the first real Gaia v7 seed table: 5000 SB1/SB1C rows, 500 correlated mass products, 5000 contamination audits, and 618 existing DESI per-HEALPix files across 372 HEALPix cells. It also exposed two concrete downstream interface defects.

This audit covers the repairs:

- the independent DPAC parity adapter now calls the official `nsstools.NssSource.covmat()` API;
- the adapter constructs the complete schema expected by nsstools and activates only finite SB1/SB1C uncertainties;
- field order, row/column order, covariance shape, and parity difference fail closed;
- per-HEALPix DESI files no longer require a `GAIA` HDU;
- direct Gaia DR3 IDs are preferred when present;
- otherwise Gaia DR3 positions and proper motions are propagated to DESI `FIBERMAP` reference epochs and matched with explicit separation and ambiguity limits;
- DESI `REF_ID` is retained as provenance and never silently treated as a Gaia DR3 ID;
- file HEALPix values may be supplied by the immutable probe plan or inferred from filenames;
- source-match mode, separation, and aggregate match diagnostics are preserved;
- all prior HOU-COMPACT tests remain in the suite.

Passing CI validates software behavior only. A fresh encrypted relay must establish live DPAC parity, DESI epoch extraction, independent visits, and orbit scoring.
