# Task 24 — Strategy registry and lifecycle

## Goal

Turn the existing strategy table into a strict production registry with immutable version identity,
audited owner approval and atomic single-version activation.

## Contract

- New versions start in `draft` and `(name, version)` cannot be overwritten.
- The only forward lifecycle is `draft → validated → approved → active → retired`.
- Activating an approved version atomically retires the previous active version with the same name.
- Invalid, skipped, reversed or concurrent transitions return stable conflict errors.
- Only owner write endpoints can approve, activate or retire a version; activation additionally
  requires the strategy name selected by frozen production configuration.
- Approval, activation and retirement are durable audit events without credentials.

## Verification

- SQLite lifecycle, duplicate, illegal transition and atomic replacement tests.
- HTTP session, Origin, CSRF, selected-strategy and audit assertions.
- Full non-network tests, Ruff, formatting and pre-commit.
