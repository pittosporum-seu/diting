# v0.8.0 Task 00 — Completion Report (Corrected)

**Date:** 2026-08-02
**Revision:** 2 (audit correction)
**Base commit:** 922cd920f570faafe76e544c1795d8336c87ecee
**Branch:** codex/v0.8.0

## Audit correction (2026-08-02)

**Issue:** Original `.gitignore` used `docs/research/artifacts/` but the canonical path
per the issue specification is top-level `research/artifacts/`. Additionally, only
`manifest.json` was re-included — `summary.json` was missing, and the directory
re-inclusion rule (`!research/artifacts/**/`) required for Git directory traversal was absent.

**Fix:**
- `.gitignore`: replaced `docs/research/artifacts/` with `research/artifacts/**` plus proper
  re-inclusion for nested directories and both `manifest.json` and `summary.json`.
- `tests/unit/test_project_hygiene.py`:
  - `test_contains_research_artifact_allow`: now checks for `research/artifacts/**`,
    `!research/artifacts/**/`, and both `manifest.json` + `summary.json` re-inclusions.
  - `test_no_large_json_in_research`: now scans `research/artifacts/` instead of `docs/research/`.

## Changes

### 1. `.gitignore` — rewritten as valid UTF-8

- Eliminated 12 NUL bytes (UTF-16LE chunk from `tmp_*.json` entry).
- Added experiment artifact ignores: `experiment/backtest_data/`, `experiment/*.csv`,
  `experiment/*.pkl`, `experiment/*.log`.
- Added broad cache/data ignores: `*.pkl`, `*.log`.
- Added research artifacts ignore with proper re-inclusion: `research/artifacts/**` is ignored
  by default, but `!research/artifacts/**/` un-ignores directories for traversal, and
  `!research/artifacts/**/manifest.json` + `!research/artifacts/**/summary.json` allow
  tracking of the two canonical summary files.
- Preserved all existing ignore patterns.

### 2. `scripts/notify-diting.ps1` — secret-free PowerShell wrapper

- Invokes WSL Ubuntu-24.04 `/home/pitto/workspace/diting/scripts/notify-diting.sh`.
- Validates WSL availability and target script existence before calling.
- Sanitizes WSL UTF-16LE output (NUL byte stripping) for reliable distro detection.
- Supports `-DryRun` switch: prints the command without executing.
- Contains no credentials, API keys, or secret patterns.
- Fails with clear error messages when WSL or target script is unavailable.

### 3. `tests/unit/test_project_hygiene.py` — hygiene test suite

17 tests across 4 classes:

| Class | Tests | Coverage |
|---|---|---|
| `TestGitignoreUTF8` | 5 | NUL bytes, valid UTF-8, not empty, experiment ignores, research artifact re-inclusion (path, directory, manifest.json, summary.json) |
| `TestNoCommittedSecrets` | 3 | .env not tracked, notify-diting.sh not tracked, only .env.example tracked |
| `TestNoRawArtifacts` | 4 | No PKL/log/experiment CSV tracked, no large JSON (>500KB) in research/artifacts |
| `TestNotifyPs1Syntax` | 5 | File exists, valid UTF-8, secret-free, has DryRun, has WSL checks |

## Verification results

### Pytest
```
uv run pytest tests/unit/test_project_hygiene.py -q
17 passed in 0.28s
```

### Ruff
```
uv run ruff check tests/unit/test_project_hygiene.py
All checks passed!
```

### PowerShell syntax check
```
Get-Command 'scripts/notify-diting.ps1' -Syntax
notify-diting.ps1 [-Title] <string> [[-Body] <string>] [-DryRun] [<CommonParameters>]
→ Syntax OK
```

### Dry-run
```
.\scripts\notify-diting.ps1 -Title "Task 00" -Body "dry run" -DryRun
[DRY RUN] Would execute:
  wsl -d Ubuntu-24.04 bash '/home/pitto/workspace/diting/scripts/notify-diting.sh' 'Task 00' 'dry run'
→ OK
```

### Git check-ignore canonical verification
```
git check-ignore -v research/artifacts/example/raw.csv
→ shows ignore rule (research/artifacts/**)

git check-ignore research/artifacts/example/manifest.json
→ exit 1 (trackable)

git check-ignore research/artifacts/example/summary.json
→ exit 1 (trackable)
→ OK
```

## Risks / open items

- `config/.env.example` was reviewed; all required placeholders (`MX_APIKEY`, `AI_API_KEY`,
  `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, etc.) are present. No changes needed.
- The real notification invocation depends on WSL `notify-diting.sh` containing valid Feishu bot
  credentials; the wrapper itself is credential-free and cannot fail with a credential leak.
