# Task 25 completion report

Status: passed.

- Added immutable dataclass contracts for experiment windows, factors, metrics, manifests and gate
  decisions.
- Bound manifests to commit/config/data/provider/gateway/result hashes, point-in-time universe
  treatment, adjustment method, factor definitions and a reproducible `uv run` command.
- Implemented canonical SHA256 sealing and durable, insert-only manifest round trips.
- Implemented every fixed mean-reversion window and promotion threshold, including the strict
  sensitivity `< 30%` and bootstrap lower-bound `> 0` boundaries.
- Failed decisions return every gate result and write nothing. Passing decisions persist the
  manifest and advance the matching new registry version only to `validated`.
- The registry now refuses validation without a persisted manifest bound to the same name/version.

Focused manifest, registry and owner verification: `22 passed`.

Full non-network regression: `600 passed, 12 deselected`.
