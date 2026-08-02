# Task 20 completion report

Status: passed.

- Added `Diting.from_config`, `get_quote`, `analyze`, `scan`, `close` and context-manager support.
- Added `ScanOrchestratorPort` to keep the Python scan signature stable for the Task 27 implementation.
- Exported `Diting`, `FetchMode`, `AnalysisProfile`, `DataResult`, `RealtimeQuote`, `AnalysisRun` and
  `ScanResult` from the package root.
- Verified `from diting import Diting` against the installed editable package.
- Inactive strategies return a typed failed scan with `NO_ACTIVE_STRATEGY`; there is no legacy scan
  fallback.

Focused verification: `19 passed`; full non-network suite: `611 passed, 79 deselected`; Ruff and
pre-commit passed. Import-boundary verification confirms that `diting.ports` does not load LiteLLM,
FastAPI, AkShare or concrete providers; the `Diting` export itself is lazy.
