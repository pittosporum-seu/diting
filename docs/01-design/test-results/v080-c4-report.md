# Checkpoint C4 — Research governance and opportunity strategy

Status: passed.

## Included commits

- `b3bf737`: strict strategy registry lifecycle and atomic activation.
- `4c7ba5a`: immutable experiment manifests and fixed validation gates.
- `ce2b6a5`: governed six-factor `mean_reversion_v1` candidate construction.
- `c049853`: active-strategy-only scanning, persistence and opportunity reads.

## Decision record

- A candidate can move only through `draft → validated → approved → active → retired`; validation
  never implies production activation.
- Reproducibility evidence binds code, config, data, Provider traces, gateway/schema versions,
  adjustment method, point-in-time universe and result hash.
- The candidate contains exactly price-vs-MA, return, volatility, RSI, volume ratio and Bollinger.
  Training IC_IR sets signed direction and normalized weights, redundant factors are pruned above
  0.7 absolute correlation, and no factor can exceed 35%.
- Production scanning loads only the selected active strategy and never falls back to the obsolete
  high-distance weights. Its cache and durable result are bound to the complete strategy identity.
- No research outcome, manifest approval or active strategy was fabricated. The opportunity surface
  therefore remains explicitly unavailable until the full external study passes and the owner
  approves and activates a version.

## Gate evidence

- Latest full non-network suite: `617 passed, 12 deselected`.
- Task 27 focused scanner/job/API/persistence suite: `44 passed`.
- Pre-commit, Ruff check, Ruff format and diff checks passed.
- No `dist_high_20` production ranking path remains in Python source.

No P0/P1 issue remains in the C4 code-governance scope. The material release dependency is a real
research report before opportunity ranking can become available; it is intentionally not a blocker
for the rest of v0.8.
