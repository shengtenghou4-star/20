# WP5 CI audit trigger

Created: 2026-07-22

This pull-request audit covers the latest main branch, including Gaia v5 contamination fields, Gaia correlation-vector decoding, correlation-aware mass products, evidence-gated triage, private pseudonymized candidate cards, and all earlier DESI/orbit infrastructure.

CI uploads `pytest-output.txt` and JUnit XML even on failure so each defect can be repaired from a preserved diagnostic artifact.

A passing result validates only the software contract on synthetic fixtures. It does not validate the live Gaia query, DESI overlap, or any astronomical candidate.
