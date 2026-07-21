# WP6 — Catalogue and literature novelty protocol

Frozen: 2026-07-22

## Purpose

The novelty audit asks whether a source, binary interpretation, or compact-companion claim has already appeared in catalogues or literature. It is a precedence check, not an astrophysical validation.

## Required coverage

The default pilot requires an explicit completed search of:

- SIMBAD for object identifiers and object types;
- VizieR for catalogue-level binary, variable, and compact-object records;
- ADS for title/abstract-level literature precedence represented by bibcodes.

A missing required service produces `novelty_audit_incomplete`, even when the available services return no match.

## Match records

Every retrieved record should preserve, when available:

- `source_id` and `solution_id`;
- service/catalogue name;
- matched object identifier;
- object type or classification;
- bibcode and title;
- angular separation;
- short notes describing why the record was retained.

The default positional ceiling is 5 arcsec. Wider records are counted as rejected and cannot establish precedence without a separately justified association.

## Conservative statuses

- `prior_compact_object_claim_found`: retained evidence mentions a black hole, neutron star, white dwarf, compact object, or explicit BH/NS candidate;
- `known_binary_without_compact_object_claim`: binary/multiple-system precedence exists without a retained compact-object claim;
- `no_prior_compact_object_claim_found`: all required services were searched and no retained compact-object or binary precedence was found;
- `novelty_audit_incomplete`: required search coverage is missing.

The vocabulary is intentionally conservative and must be sensitivity-audited before publication. False positives are reviewed manually from the preserved identifiers and bibcodes.

## Reproducible command

```bash
python scripts/audit_novelty.py \
  outputs/followup_sources.csv \
  private/novelty_matches.csv \
  --searched-service SIMBAD \
  --searched-service VizieR \
  --searched-service ADS \
  --output outputs/novelty_audit.csv
```

The command emits one audit row per source/solution and a manifest with input hashes, coverage, row counts, and status counts. A clean novelty status never proves that an object is a compact companion or that a discovery claim is valid.
