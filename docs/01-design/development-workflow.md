# Diting v0.8 development workflow

This how-to complements `AGENTS.md`; it does not redefine architecture.

## 1. Start from a bounded Issue

An implementation Issue names the Accepted design section, exact behavioral contract, expected file
scope, failure semantics and executable acceptance checks. Inspect the current diff first and keep
unrelated user changes intact.

Use a small vertical slice: domain/port → application behavior → adapter/interface mapping → focused
tests. Avoid broad rewrites and avoid compatibility shims for removed v0.8 contracts.

## 2. Preserve the boundaries

```text
interfaces → application → domain + ports
adapters   → domain + ports
bootstrap  → all concrete assembly
```

- data calls go through `CachedMarketDataGateway`;
- analysis goes through `DataSnapshotBuilder` and `AnalysisOrchestrator`;
- opportunity ranking loads only an active strategy through `ScanOrchestrator`;
- core boundaries use frozen dataclasses, while Pydantic stays at HTTP boundaries;
- engine registration is explicit; package imports have no discovery/network side effect.

## 3. Verify the slice

Run focused tests first, then the release gates:

```bash
uv run pre-commit run --all-files
uv run ruff check src/ tests/ browser_tests/ scripts/validate-api.py
uv run ruff format --check src/ tests/ browser_tests/ scripts/validate-api.py
uv run pytest tests/ -m "not network" -q
uv run python scripts/validate-api.py --check
find frontend -type f -name '*.js' -print0 | xargs -0 -n1 node --check
find scripts -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
uv run pytest browser_tests/ -q
```

Network tests and full research studies run separately. Network flakiness does not block core code,
but strategy validation requires the complete reproducible study.

## 4. Record evidence

Each task writes a concise report under `test-results/` with changed behavior, exact checks, outcomes
and residual risk. Update `tasks/todo.md` only after the implementation and gates pass. Checkpoint
reports summarize constituent commits rather than inventing new evidence.

## 5. Review and publish

Review security, migration/rollback, data bypasses, swallowed exceptions, scoring semantics, strategy
governance and browser errors. Open a PR to `verify`; required CI jobs may not be skipped by path
filters. Production deployment is allowed only from a clean commit exactly equal to fetched
`origin/verify` after remote CI is green. Follow the
[release how-to](../ops/deploy-checklist.md) for candidate, Owner tunnel verification, rollback
rehearsal, promotion and observation.
