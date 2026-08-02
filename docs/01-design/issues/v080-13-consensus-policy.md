# Task 13 — Consensus policy and deterministic verdict

## Goal

Make evidence sufficiency explicit and eliminate every neutral-score fallback from the new kernel.

## Policy

- Only schema-valid `succeeded` runs with matching names/versions/scores participate.
- Require at least two positive-weight successes, at least one deterministic engine and at least
  50% of the planned positive weight.
- Persist the actual weight snapshot, coverage, failures and score conflicts.
- Insufficient evidence returns `analysis_score=None` and a machine-readable reason.
- Verdict only labels and explains consensus; it cannot alter a score or create a positive result
  from insufficient evidence.

## Verification

Table-driven tests cover every threshold, invalid runs, conflicts, weight snapshots and verdict
behavior.
