# Implementation Plan: 谛听 v0.8.0

## Overview

以 `docs/01-design/v0.8.0-system-design.md` 为 Accepted 架构基线，将现有多入口、
多缓存和多评分语义的实现收敛为模块化单体。实现按纵向切片推进；每项任务最多约
5 个实现/测试文件，并在每 2–4 项后执行一次全量 checkpoint。

## Architecture decisions

- Windows 工作区是唯一代码源；WSL 只执行现有飞书通知脚本。
- CLI、Python API、HTTP 和后台任务共享 bootstrap、Data Gateway 与 Orchestrator。
- 业务状态写入 `diting.db`，可丢弃数据缓存写入 `diting_cache.db`。
- v0.8 直接切断旧 API/CLI 契约；公共读取可匿名，写入和昂贵计算使用 owner 会话。
- 失败是失败，不映射为 50 分；机会榜只读取人工激活的策略版本。

## Dependency graph

```text
version/config/domain/ports
  -> persistence/cache store
  -> CachedMarketDataGateway
  -> snapshot + engines + consensus
  -> AnalysisOrchestrator + JobService
  -> auth + API/Python/CLI
  -> frontend
  -> strategy registry + research validation + ScanOrchestrator
  -> contracts/CI/browser/deploy
```

## Task list

### Phase 0 — Governance and recoverability

#### Task 00: Repository hygiene and notification bridge

**Acceptance criteria:**
- `.gitignore` is valid UTF-8 without NUL and excludes raw experiment/runtime artifacts.
- A tracked secret-free Windows wrapper invokes the existing WSL notification script.
- Hygiene tests reject committed secrets and oversized raw research artifacts.

**Verification:** focused pytest, PowerShell syntax check, WSL wrapper dry-run.

**Dependencies:** none. **Scope:** 3–5 files.

#### Task 00b: Make repository gates reproducible on Windows

**Acceptance criteria:**
- Text files have an explicit LF policy that is stable with system `core.autocrlf=true`.
- Ruff pre-commit hooks match the release gate scope (`src/` and `tests/`).
- Two consecutive `pre-commit run --all-files` executions pass without modifying files.

**Verification:** pre-commit twice, full source/test ruff, non-network tests and diff audit.

**Dependencies:** Task 00. **Scope:** 2–3 policy/test files plus mechanical whitespace normalization.

#### Task 01: Version and strict configuration foundation

**Acceptance criteria:**
- `pyproject.toml` is the only package version source and reports `0.8.0`.
- Configuration precedence is CLI > environment > YAML > defaults.
- Unknown configuration keys fail with a useful validation error.

**Verification:** configuration/version unit tests and ruff.

**Dependencies:** Task 00b. **Scope:** 3–5 files.

#### Task 02: Domain contracts and ports

**Acceptance criteria:**
- Frozen domain dataclasses cover data results, traces, freshness, snapshots and runs.
- Provider/LLM/sandbox/cache/store/clock contracts are protocols without implementations.
- Core business boundaries do not expose dict/DataFrame.

**Verification:** schema and import-boundary unit tests.

**Dependencies:** Task 01. **Scope:** 3–5 files.

#### Task 03: Single bootstrap composition root

**Acceptance criteria:**
- One bootstrap path constructs CLI, Web and Python API dependencies.
- Only bootstrap/adapters import concrete providers.
- Application code can be built with in-memory test doubles.

**Verification:** bootstrap and AST architecture tests.

**Dependencies:** Tasks 01–02. **Scope:** 3–5 files.

### Phase 1 — Persistence and cached data access

#### Task 04: Idempotent database migrations

**Acceptance criteria:**
- Separate durable and cache databases have versioned, idempotent migrations.
- Existing databases are backed up before first migration.
- Migration failure makes readiness fail without corrupting the source database.

**Verification:** empty/legacy/repeated/failure migration tests.

**Dependencies:** Tasks 02–03. **Scope:** 3–5 files.

#### Task 05: L1/L2 cache store and canonical keys

**Acceptance criteria:**
- Bounded L1 and SQLite L2 honor per-entry TTL, stale bounds and schema version.
- Canonical keys include all request dimensions and are stable across processes.
- Negative cache distinguishes transient failures from not-found results.

**Verification:** cache policy, eviction, serialization and restart tests.

**Dependencies:** Task 04. **Scope:** 3–5 files.

#### Task 06: Quote gateway vertical slice

**Acceptance criteria:**
- Quote calls return `DataResult[RealtimeQuote]` for all fetch modes.
- Same-key concurrency causes one upstream call; successful responses populate L1/L2.
- Provider fallback, retries and traces are explicit.

**Verification:** deterministic fake-provider integration tests.

**Dependencies:** Task 05. **Scope:** 3–5 files.

#### Task 07: Historical, fundamental and fund-flow gateway slice

**Acceptance criteria:**
- Historical data is normalized and schema-versioned before compressed storage.
- Historical, financial and fund-flow requests share the same cache/freshness semantics.
- `FRESH_REQUIRED`, `CACHE_PREFERRED`, `CACHE_ONLY` and force refresh are covered.

**Verification:** focused gateway tests including stale-if-error.

**Dependencies:** Task 06. **Scope:** 3–5 files.

#### Task 08: Catalog, trading calendar and market phases

**Acceptance criteria:**
- Catalog and calendar requests use the gateway and configured TTLs.
- Trading phases derive from an exchange/provider calendar, never civil workdays.
- `post_close_settling` triggers one final-refresh opportunity.

**Verification:** weekend, holiday, settling and next-open tests.

**Dependencies:** Task 06. **Scope:** 3–5 files.

#### Task 09: Remove data-access bypasses

**Acceptance criteria:**
- CLI, Stock, Scan and Dashboard paths no longer build providers or query cache tables.
- Concrete-provider imports outside adapters/bootstrap fail CI.
- Equivalent CLI/Web quote calls have identical `DataResult` semantics.

**Verification:** AST guard and service integration tests.

**Dependencies:** Tasks 07–08. **Scope:** split into service-specific patches of ≤5 files.

### Phase 2 — Analysis kernel

#### Task 10: DataSnapshotBuilder

**Acceptance criteria:** immutable snapshot contains provider traces, completeness and hash;
analysis uses `FRESH_REQUIRED`; identical inputs produce identical hashes.

**Verification:** snapshot unit/integration tests.

**Dependencies:** Task 09. **Scope:** 3–5 files.

#### Task 11: Explicit engine registry and deterministic technical engine

**Acceptance criteria:** engine selection is explicit; technical indicators have their own
engine; Verdict is a post-consensus interpreter; VMD weight is zero.

**Verification:** registry, plan and scoring unit tests.

**Dependencies:** Task 10. **Scope:** 3–5 files.

#### Task 12: Strict structured AI results

**Acceptance criteria:** each AI engine validates a strict schema; empty/invalid/out-of-range
output becomes a failed EngineRun; production never executes generated code by default.

**Verification:** parser boundary and malicious/invalid output tests.

**Dependencies:** Task 11. **Scope:** 3–5 files.

#### Task 13: Consensus policy

**Acceptance criteria:** consensus requires two successes, one deterministic engine and 50%
weight coverage; insufficient evidence returns `analysis_score=None`; conflict details persist.

**Verification:** table-driven consensus tests.

**Dependencies:** Tasks 11–12. **Scope:** 2–4 files.

#### Task 14: AnalysisOrchestrator profiles

**Acceptance criteria:** standard/deep produce the specified plans; config/strategy/snapshot and
deadline are frozen; CLI/Web/Python call the same orchestrator.

**Verification:** profile and cross-interface parity tests.

**Dependencies:** Tasks 10–13. **Scope:** 3–5 files.

#### Task 15: Persistent bounded JobService

**Acceptance criteria:** queue limits and concurrency match the design; dedupe/deadline/progress/
cancel work; running jobs are marked interrupted after restart.

**Verification:** concurrency, queue-full, cancellation and restart tests.

**Dependencies:** Tasks 04 and 14. **Scope:** 3–5 files.

#### Task 16: Post-persist report and notification tasks

**Acceptance criteria:** AnalysisRun commits before side effects; report/notification failures do
not alter analysis status; retry/audit details persist.

**Verification:** failure-injection tests.

**Dependencies:** Task 15. **Scope:** 3–5 files.

### Phase 3 — Auth, public interfaces and frontend

#### Task 17: Owner session, CSRF and origin protection

**Acceptance criteria:** hashed token login, 12-hour secure cookie, logout, CSRF and Origin checks;
no secret is logged or returned.

**Verification:** auth security tests.

**Dependencies:** Tasks 03–04. **Scope:** 3–5 files.

#### Task 18: Versioned envelope and public v1 API

**Acceptance criteria:** public endpoints live at `/api/v1`; envelopes contain request/cache/
freshness metadata; errors omit production stacks.

**Verification:** contract tests for health/search/quote/completed analyses/dashboard/opportunities.

**Dependencies:** Tasks 09, 14 and 17. **Scope:** 3–5 files.

#### Task 19: Owner v1 API and rate limiting

**Acceptance criteria:** protected CRUD/jobs/settings/cache/strategy endpoints enforce auth;
configured public/login/analysis/scan limits return stable error codes.

**Verification:** permission and rate-limit tests.

**Dependencies:** Tasks 15, 17–18. **Scope:** split by endpoint group, ≤5 files each.

#### Task 20: Stable Python facade

**Acceptance criteria:** `Diting.from_config`, quote/analyze/scan, context manager and close are
public and use bootstrap; public types are exported intentionally.

**Verification:** Python API lifecycle/parity tests.

**Dependencies:** Tasks 14–15. **Scope:** 3–5 files.

#### Task 21: v0.8 CLI

**Acceptance criteria:** canonical commands are analyze/quote/scan/compare/watchlist/strategy/serve;
`diting CODE` maps to standard; removed aliases fail clearly.

**Verification:** Click runner tests and CLI/Python parity.

**Dependencies:** Tasks 14–15 and 20. **Scope:** 3–5 files.

#### Task 22: Frontend API client, auth and state machine

**Acceptance criteria:** one v1 client handles envelopes/auth/CSRF; pages render loading/empty/
stale/error states; no direct page fetch or diagnostic marker remains.

**Verification:** JS syntax plus browser auth/navigation checks.

**Dependencies:** Tasks 18–19. **Scope:** split into client/shell and page slices, ≤5 files each.

#### Task 23: Remove legacy HTTP/Jinja flow

**Acceptance criteria:** old API paths return `410 API_VERSION_REMOVED`; legacy business handlers
and templates are unreachable; Caddy-facing prefix is documented as `/api/diting/v1`.

**Verification:** old-path matrix and route inventory tests.

**Dependencies:** Tasks 18–22. **Scope:** 3–5 files.

### Phase 4 — Strategy governance and research

#### Task 24: Strategy registry and lifecycle

**Acceptance criteria:** transitions enforce draft→validated→approved→active→retired; only owner
can approve/activate; activation is audited and exactly one compatible active version is selected.

**Verification:** lifecycle/authorization/migration tests.

**Dependencies:** Tasks 04 and 19. **Scope:** 3–5 files.

#### Task 25: Experiment manifest and validation gates

**Acceptance criteria:** manifests include data/provider/adjustment/universe/hash metadata; fixed
train/validation/OOS windows and all promotion gates are reproducible; leakage checks are mandatory.

**Verification:** fixture-based gate and manifest tests.

**Dependencies:** Tasks 07–08 and 24. **Scope:** 3–5 files.

#### Task 26: mean_reversion_v1 candidate

**Acceptance criteria:** only approved factor families participate; correlations and IC_IR weights
use training data; max factor weight is 35%; VMD and old `dist_high_20: 0.85` are absent.

**Verification:** deterministic factor/weight tests and source search guard.

**Dependencies:** Task 25. **Scope:** 3–5 files.

#### Task 27: Active-strategy ScanOrchestrator

**Acceptance criteria:** scans require an active strategy; otherwise return empty items plus
`NO_ACTIVE_STRATEGY`; cache keys include strategy/factor/data/config versions.

**Verification:** inactive/active/retired and cache isolation tests.

**Dependencies:** Tasks 24–26. **Scope:** 3–5 files.

### Phase 5 — Contracts, quality and deployment

#### Task 28: OpenAPI and CI contract gates

**Acceptance criteria:** checked-in OpenAPI equals runtime generation; workflows cover all relevant
paths; architecture/config/frontend checks cannot be skipped by path filters.

**Verification:** local contract generator/check and workflow lint.

**Dependencies:** Tasks 18–27. **Scope:** 3–5 files.

#### Task 29: Real Chromium journeys

**Acceptance criteria:** five pages, login/logout, search, watchlist, analysis progress and strategy
state pass in Chromium without console/page errors.

**Verification:** Playwright run against a local server.

**Dependencies:** Tasks 22–23 and 27. **Scope:** 3–5 files.

#### Task 30: Release-safe VPS deployment

**Acceptance criteria:** deterministic checksummed release, non-root service, candidate port,
database-copy migrations, atomic switch and rollback are automated without insecure SSH flags.

**Verification:** shell syntax, dry-run, candidate smoke and documented rollback rehearsal.

**Dependencies:** Tasks 28–29. **Scope:** split into packaging/service/deploy checks, ≤5 files each.

#### Task 31: Documentation and release review

**Acceptance criteria:** Diátaxis docs match actual commands/contracts; historical designs are marked
superseded; README facts are generated/verified; final implementation review has no P0/P1.

**Verification:** link/command checks and full release checklist.

**Dependencies:** all prior tasks. **Scope:** documentation-only slices.

## Checkpoints

- **C0 (Tasks 00–03):** clean architecture foundation, focused tests, full non-network baseline.
- **C1 (Tasks 04–09):** all data access uses the gateway; cache concurrency/fallback verified.
- **C2 (Tasks 10–16):** cross-interface analysis parity and no fake neutral scores.
- **C3 (Tasks 17–23):** auth/API/CLI/Python/frontend flows pass locally.
- **C4 (Tasks 24–27):** inactive strategy is safe; candidate is traceable and gated.
- **C5 (Tasks 28–31):** all gates pass, PR reviewed, candidate deployed and rollback rehearsed.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Large breaking rewrite | High | Vertical slices, compatibility cut only at Task 23 |
| SQLite contention | High | One worker, WAL/busy timeout, bounded queues, concurrency tests |
| Provider instability | High | Fake-provider tests, explicit traces, stale-if-error and circuit breaker |
| Research leakage/overfit | High | Point-in-time universe, fixed windows, manifest and activation gate |
| Frontend drift | Medium | Generated OpenAPI comparison and real Chromium journeys |
| VPS runtime mismatch | High | Candidate port and isolated Python 3.12 release before atomic switch |

## Open questions

None. Product, compatibility, auth, data, strategy and deployment decisions are locked by the
approved v0.8.0 plan.
