# v0.8.0 Task 00 — Repository hygiene and notification bridge

## Design references

- `docs/01-design/v0.8.0-system-design.md`
- `tasks/plan.md` Task 00
- `AGENTS.md` sections 0.5, 3 and 7

## Scope

Modify or create only these implementation/test files unless a tiny fixture is essential:

1. `.gitignore`
2. `scripts/notify-diting.ps1`
3. `tests/unit/test_project_hygiene.py`
4. `config/.env.example` (only if missing placeholders must be documented)

Do not edit design documents, `AGENTS.md`, README, production credentials or WSL files.

## Requirements

- Rewrite `.gitignore` as valid UTF-8 without NUL bytes.
- Ignore raw `experiment/` inputs/outputs, caches, PKL/CSV/logs and local diagnostic artifacts.
- The canonical path is the top-level `research/artifacts/` (not `docs/research/artifacts/`). Ignore
  its contents by default, but use valid Git re-inclusion rules so nested directories plus
  `manifest.json` and `summary.json` can actually be tracked. Reject oversized research artifacts
  in the hygiene test.
- Add a secret-free PowerShell wrapper that calls Ubuntu-24.04
  `/home/pitto/workspace/diting/scripts/notify-diting.sh` with title/body. Support `-DryRun` so CI and
  local verification do not send messages. Do not read, print or copy credentials.
- The wrapper must fail clearly when WSL or the target script is unavailable.

## Acceptance and verification

- `uv run pytest tests/unit/test_project_hygiene.py -q`
- `uv run ruff check tests/unit/test_project_hygiene.py`
- PowerShell parse check for `scripts/notify-diting.ps1`
- `scripts/notify-diting.ps1 -Title "Task 00" -Body "dry run" -DryRun`
- `git check-ignore -v research/artifacts/example/raw.csv` must show an ignore rule, while
  `git check-ignore research/artifacts/example/manifest.json` and `summary.json` must return 1.
- Run the real notification only after all checks pass.

## Completion protocol

Write `docs/01-design/test-results/v080-task00-report.md`, append one valid JSON line to
`docs/01-design/test-results/codewhale-status.jsonl`, then call the wrapper to notify 海桐. The
report/status files are required outputs and are exempt from the implementation-file limit.
