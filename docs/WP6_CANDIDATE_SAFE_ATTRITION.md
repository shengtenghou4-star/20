# WP6 — candidate-safe attrition and coverage protocol

Frozen: 2026-07-22

## Purpose

HOU-COMPACT must report how the frozen 5,000-source cohort changes at every evidence gate without revealing source identifiers before the release decision. A final candidate count alone is insufficient because it hides whether the dominant limitation is Gaia quality, DESI coverage, stellar inference, contamination, Roche geometry, or a genuinely empty high-mass tail.

## Sequential accounting

Every row is assigned to its first blocking stage or one final follow-up stage:

1. `gaia_quality_hold`;
2. `desi_orbit_hold`;
3. `mass_inference_hold`;
4. `contamination_resolution_hold`;
5. `roche_geometry_hold`;
6. one of the final orbit-supported follow-up strata.

For each hold stage the report records:

- population entering the gate;
- population first held at the gate;
- population advancing to the next gate;
- held fraction among entrants;
- advanced fraction of the original cohort.

The population advancing beyond the Roche gate must equal the sum of:

- `orbit_supported_lower_mass`;
- `high_minimum_mass_followup`;
- `very_high_minimum_mass_followup`.

Any mismatch, missing stage label, or unknown stage fails closed.

## Additional candidate-safe outcomes

The report also includes:

- every stage count, including explicit zeros;
- semicolon-delimited blocker and caution frequencies;
- counts with 0, 1, 2, and 3+ clean DESI epochs;
- q16 minimum-companion-mass counts above 1.4, 3, 5, and 8 solar masses;
- the same mass-threshold counts after all current evidence gates.

These thresholds are descriptive follow-up strata and must not be described as object classes.

## Confidentiality contract

Outputs contain no Gaia source ID, Gaia DR2 bridge ID, DESI TARGETID, coordinates, epoch velocities, row ranks, or candidate-level measurements. Input and output SHA256 hashes preserve reproducibility. Source-level products remain in the encrypted evidence relay.

## Null-result interpretation

- A large `gaia_quality_hold` population means the catalogue tail is dominated by weak or flagged published solutions.
- A large `desi_orbit_hold` population may reflect missing coverage, too few independent visits, poor phase coverage, or disagreement with the fixed Gaia orbit; these sub-causes remain separately visible in blocker counts.
- A large `mass_inference_hold` population quantifies missing or weak stellar information rather than astrophysical rejection.
- A large contamination or Roche hold population demonstrates how physical-consistency and multiplicity requirements reduce the Gaia-only high-mass tail.
- Zero rows passing all gates is a valid population-null result when every earlier denominator and failure mode is reported.

## Reproducible command

```bash
python scripts/summarize_followup_attrition.py \
  outputs/followup_triage.csv \
  --output outputs/followup_attrition_summary.json \
  --flow-output outputs/followup_attrition_summary.flow.csv
```

The JSON is manuscript-facing and candidate-safe. The CSV supplies the fixed stage order for tables and flow diagrams.
