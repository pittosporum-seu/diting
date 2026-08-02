# v0.8.0 Task 09 — Remove data-access bypasses

## References

- `docs/01-design/v0.8.0-system-design.md` dependency rules
- `tasks/plan.md` Task 09

## Slices

1. Add an internal interface adapter for legacy analysis consumers while preserving typed
   `DataResult` acquisition underneath.
2. Inject the runtime gateway into CLI and Web services; remove Provider construction and raw
   quote/history cache-table access from Stock, Scan, Watchlist and Dashboard paths.
3. Replace direct fund-flow Provider use, empty the AST exception set, and add CLI/Web parity tests.

The adapter is transitional internal code, not a public v0.8 compatibility contract; Task 14/23
remove the remaining legacy service and HTTP shapes.

## Verification

- `uv run pytest tests/unit/test_architecture_boundaries.py tests/integration/test_services_dataflow.py -q`
- CLI/Web quote results share the same gateway request, cache state and Provider traces.
- `rg` finds no concrete Provider construction outside `bootstrap.py` and data adapters.
