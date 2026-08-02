# Task 26 completion report

Status: passed.

- Added the exact six-family `mean_reversion_v1` candidate pool and typed training statistics.
- Directions use signed training IC_IR. Weight magnitudes use absolute training IC_IR only.
- Requires all 15 pairwise correlations; absolute correlation above 0.7 removes the lower-IC_IR
  factor deterministically.
- Added capped water-filling normalization with a 35% per-factor maximum and a minimum of three
  independent factors.
- Bound production definitions to cross-sectional ranks, explicit missing-value handling, Top20,
  twenty trading days and 40bp round-trip cost.
- Both experiment promotion and registry activation reject malformed or unapproved factor
  definitions.
- Removed the obsolete hard-coded high-distance ranking implementation from production source.
- No candidate manifest, approval or active strategy was fabricated; full research remains an
  external gate and the opportunity surface therefore remains explicitly unavailable.

Focused candidate, governance, registry, owner and isolated legacy-service verification:
`57 passed`.

Full non-network regression: `607 passed, 12 deselected`.
