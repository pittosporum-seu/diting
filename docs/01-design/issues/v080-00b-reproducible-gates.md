# v0.8.0 Task 00b — Reproducible Windows/pre-commit gates

## Why this task exists

The first strict checkpoint found two baseline policy mismatches:

1. system Git has `core.autocrlf=true`, while `.gitattributes` only pins Python/shell files; the
   `mixed-line-ending --fix=lf` hook rewrites many historical files on every full run;
2. the release plan requires ruff for `src/` and `tests/`, but pre-commit currently lints all legacy
   research/operations scripts, which contain pre-existing experimental style debt.

This task fixes the policy; it must not hide source/test failures or perform semantic script edits.

## Design references

- `AGENTS.md` section 4
- `tasks/plan.md` Task 00b and Checkpoint C0
- User-approved Phase 5 gate commands

## Scope

Policy/test files:

1. `.gitattributes`
2. `.pre-commit-config.yaml`
3. `tests/unit/test_project_hygiene.py`

The hooks may mechanically normalize whitespace/EOF/line endings in tracked text files. Those
mechanical changes are an explicit exception to the 5-file limit. Do not reformat or change the
semantics of legacy `scripts/`, application code, docs, vendored/minified JS or generated assets.

Do not edit `AGENTS.md`, design documents, README or credentials.

## Requirements

- Define a repository-wide LF policy for text while keeping known binary assets binary and allowing
  vendored/minified files to avoid unnecessary content rewrites.
- Scope both ruff hooks to `src/` and `tests/`, exactly matching the release commands. This is not an
  exclusion for application/test code.
- Extend hygiene tests to assert the line-ending policy and ruff hook scope.
- Run pre-commit once to apply only necessary mechanical fixes; audit `git diff --check` and sampled
  diffs. Revert any semantic/formatter changes outside `src/`/`tests/`.
- Run pre-commit a second time; it must pass and make no further changes.

## Acceptance and verification

- `uv run pytest tests/unit/test_project_hygiene.py -q`
- `uv run pre-commit run --all-files` twice; second run leaves `git status` unchanged.
- `uv run ruff check src/ tests/`
- `uv run ruff format --check src/ tests/`
- `git diff --check`
- `uv run pytest tests/ -m "not network" -q`
- all `frontend/**/*.js` pass `node --check`.

## Completion protocol

Write `docs/01-design/test-results/v080-task00b-report.md`, append valid JSONL status and notify 海桐
through `scripts/notify-diting.ps1`. Report any baseline failure exactly; do not claim success if a
second pre-commit run still modifies files.
