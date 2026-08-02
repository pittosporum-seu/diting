# Task 26 — `mean_reversion_v1` candidate

## Goal

Provide the deterministic factor-selection and weighting code needed to turn validated training
statistics into a typed production definition, without inventing research results or activating a
strategy.

## Contract

- The input pool is exactly price-vs-MA, return, volatility, RSI, volume ratio and Bollinger.
- Directions and weight magnitudes come only from signed training IC_IR.
- A complete training correlation matrix is mandatory. For absolute correlation greater than 0.7,
  the lower-absolute-IC_IR factor is removed; ties resolve by canonical factor order.
- Remaining absolute IC_IR values are normalized with deterministic water-filling and no factor may
  exceed 35%; at least three independent factors must remain.
- Production definitions use cross-sectional ranks, exclude missing period/assets, Top20, twenty
  trading days and 40bp round-trip cost.
- Registry activation rejects missing, unknown, duplicate, misdirected, unnormalized or overweight
  definitions even if a version was approved.
- Context-only signal decomposition and the obsolete high-distance factor are absent from the
  candidate; the obsolete hard-coded ranking implementation is removed from production source.
- This task creates no active manifest because the full external-data research report has not been
  run and approved.

## Verification

- Deterministic pool, sign, correlation boundary/pruning and capped-weight tests.
- Incomplete input and invalid activation tests.
- Production source guard for the obsolete factor and candidate-source guard for context-only input.
- Full non-network tests, Ruff, formatting and pre-commit.
