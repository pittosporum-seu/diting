# Task 25 — Experiment manifest and validation gates

## Goal

Require an immutable, reproducible evidence package before a research candidate can enter the
strategy registry's `validated` state.

## Contract

- The manifest binds experiment identity, hypothesis, commit/config hashes, point-in-time universe,
  listing/delisting treatment, Data Gateway request hashes, Provider trace, adjustment method, data
  snapshot, factor definitions, fixed windows, metrics, result hashes and reproduction command.
- The content hash excludes only its own `manifest_hash` field; post-seal edits fail validation.
- Fixed windows are training 2022–2024, validation 2025 and OOS 2026-01-01 through 2026-07-31.
- Promotion requires OOS Rank IC ≥ 0.05, IC_IR ≥ 0.5, bootstrap lower bound > 0, net 20-day
  excess ≥ 0.5%, sensitivity < 30%, coverage ≥ 90%, cross-section ≥ 500, Top20, 20 trading days,
  40bp round-trip cost and no future-data leakage.
- Passing persists the manifest and advances a newly registered draft only to `validated`; approval
  and activation remain explicit owner actions.
- Failed gates produce a complete typed decision and perform no durable promotion writes.

## Verification

- Passing round-trip fixture and threshold boundary matrix.
- Fixed-window, tamper, point-in-time universe and gateway-provenance failures.
- Full non-network tests, Ruff, formatting and pre-commit.
