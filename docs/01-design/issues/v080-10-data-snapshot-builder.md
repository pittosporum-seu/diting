# Task 10 — DataSnapshotBuilder

## Goal

Provide one immutable, traceable data snapshot for every analysis run. All four data slices use
`FRESH_REQUIRED`, the request deadline and the shared `DataGateway`.

## Contract

- Normalize A-share symbols before reading data.
- Preserve missing data as `None`; never manufacture zero-valued market data.
- Aggregate provider traces and warnings from every `DataResult`.
- Compute completeness from quote, history, financial and fund-flow availability.
- Hash canonical business data, data times and request identities; exclude cache tier and retry
  timestamps so operational noise does not change the snapshot identity.

## Verification

- Unit tests cover fetch policy/deadline propagation, trace aggregation, missing data and stable
  hashing.
- Ruff and the non-network test suite must pass at Checkpoint C2.
