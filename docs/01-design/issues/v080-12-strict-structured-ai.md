# Task 12 — Strict structured AI results

## Goal

Replace production code-generation behavior with injected, JSON-Schema-constrained LLM engines.

## Rules

- Wyckoff, CANSLIM and Buffett have separate strict schemas with `extra=forbid`.
- Empty, fenced, malformed, incomplete, extra-field and out-of-range outputs raise
  `INVALID_STRUCTURED_OUTPUT`; no parser repair and no neutral-score fallback are allowed.
- Dimension-based engines validate that the final score matches their component totals.
- Production engines consume bounded snapshot facts and have no sandbox dependency.
- The LiteLLM port requests provider-native strict JSON schema output.

## Verification

Focused tests exercise valid conversion and all invalid response classes without a network call.
