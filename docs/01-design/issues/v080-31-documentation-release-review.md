# Task 31 — Documentation and release review

## Goal

Make every active entry document describe the implemented v0.8 system, clearly quarantine historical
designs and complete an automated release-fact review before opening the PR.

## Contract

- README is a v0.8 tutorial/overview with actual CLI, Python, engine, API, security, strategy and
  quality semantics; it contains no historical test-count claim.
- Documentation has one Diátaxis index, current design status index, first-analysis tutorial,
  configuration reference, engine/strategy How-to and release How-to.
- API and development workflow references contain only v0.8 commands and explicit registration.
- Every pre-v0.8 design family is marked Superseded in the design index.
- Research status says governance code is implemented but no real strategy has been validated,
  approved or activated.
- Automated tests derive version/CLI/OpenAPI facts, resolve every relative link in active docs and
  reject old deployment/API/engine-registration claims.
- Final review checks architecture, security, migration, score semantics, data bypasses, exception
  swallowing, strategy governance, browser behavior and deployment rollback for P0/P1 findings.

## Verification

- Documentation contract tests and relative-link checks.
- Full pre-commit/Ruff/core/OpenAPI/JavaScript/shell/Chromium release gates.
- Git diff and tracked-file review; final C5 report records external CI/PR/deployment dependencies
  truthfully.
