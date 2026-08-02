# Extend the v0.8 analysis kernel

An engine consumes the run's frozen `DataSnapshot`; it does not fetch data, read raw configuration
or discover itself through import side effects.

## 1. Implement the explicit contract

```python
from diting.engines.kernel import SnapshotAnalysisEngine
from diting.enums import EngineMode
from diting.schema import DataSnapshot, EngineCapabilities, EngineContext, EngineResult


class MyEngine(SnapshotAnalysisEngine):
    name = "my_engine"
    version = "1.0.0"
    mode = EngineMode.DETERMINISTIC

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            required_data=("historical",),
            min_history_bars=60,
            deterministic=True,
            timeout_seconds=5,
        )

    def analyze(self, snapshot: DataSnapshot, context: EngineContext) -> EngineResult:
        # Validate typed snapshot data and return a typed result or raise a typed failure.
        ...
```

Do not call a Provider, return a dict, mutate the snapshot, catch every exception or substitute 50
for failure.

## 2. Register at the composition root

Add the concrete instance to the explicit `EngineRegistry` construction in `bootstrap.py`. There is
no decorator/import discovery. Add its profile name and weight to strict configuration only if it is
intended for that production profile.

LLM engines receive an injected `LLMPort` and must validate a strict Pydantic output schema. Code
execution requires an injected `SandboxPort` and explicit research enablement; it is not the default
production AI path.

## 3. Test the boundary

- exact capabilities and required snapshot slices;
- deterministic fixed-input output or strict structured parsing;
- missing/invalid data and timeout behavior;
- registry duplicate/name behavior;
- profile planning and consensus coverage;
- AST dependency rule: no concrete Provider import outside adapters/bootstrap.

Run the full gates from `CONTRIBUTING.md` before changing the engine plan.
