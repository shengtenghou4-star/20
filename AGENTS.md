# HOU-COMPACT Agent Rules

## Scientific control

- Never describe an object as a black hole, neutron star, or compact-object detection from a catalogue mass estimate alone.
- Preserve failed candidates and negative results with machine-readable rejection reasons.
- Do not begin blind candidate publicity before control samples and orbit-prediction tests pass.
- Separate measured values, derived values, priors, and interpretation in every output table.
- Treat survey release notes and known systematics as part of the data, not optional commentary.

## Repository discipline

- Commit code, query text, tests, manifests, compact derived tables, candidate cards, and research notes.
- Do not commit raw multi-gigabyte survey files, tokens, credentials, or unlicensed data.
- Every data-producing command must record input URLs, checksums, row counts, package versions, and Git SHA.
- Work on an `agent/<task>` branch for substantial changes; open a PR with tests and a scientific summary.
- Do not overwrite frozen queries or protocols. Add a new version and explain the change.

## Required validation

Before merging scientific code:

1. add deterministic unit tests;
2. run `ruff check src tests scripts`;
3. run `pytest`;
4. test on synthetic data with a known answer;
5. document assumptions and known failure modes.

## Candidate language

Allowed internal labels:

- `seed`
- `rv-variable`
- `orbit-consistent`
- `dark-companion-plausible`
- `high-priority-follow-up`

The words `confirmed`, `discovery`, `black hole`, and `neutron star` require explicit evidence review and a documented approval gate.
