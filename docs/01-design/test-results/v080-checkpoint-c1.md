# v0.8.0 Checkpoint C1

Status: passed

Date: 2026-08-02

## Acceptance evidence

- `diting.db` and `diting_cache.db` have separate, checksummed and idempotent migrations.
- Existing databases are backed up and SHA256-verified before their first v0.8 migration.
- L1 is bounded; L2 is persistent; cache payloads are typed, compressed and schema-versioned.
- All six market-data capabilities run through one gateway with canonical request keys.
- Same-key requests use single-flight; retry, fallback, negative cache, stale-if-error and
  persistent circuit state have deterministic tests.
- Exchange phases come only from Provider calendar sessions; unknown is explicit.
- CLI and Web no longer construct Providers, import the legacy repository, or access raw quote/
  history cache tables.
- Full non-network gate: `535 passed, 79 deselected`; pre-commit/Ruff/JS syntax passed.

## Known follow-up risks

- Legacy analysis and scan scoring shapes still exist above the data boundary; C2/C4 replace them
  with immutable snapshots, explicit engines and active strategy governance.
- FastAPI event hooks and Python sqlite timestamp conversion emit deprecation warnings; Phase 3/5
  must remove them before release.
- The internal `GatewayLegacyView` converts immutable bars to DataFrame only at old presentation
  consumers and must be deleted by Task 23.
