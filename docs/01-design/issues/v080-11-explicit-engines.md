# Task 11 — Explicit engine registry and technical engine

## Goal

Start the v0.8 engine path without decorator/import discovery. The composition root will pass an
explicit immutable `EngineRegistry` to the orchestrator.

## Decisions

- The new snapshot contract is isolated as `SnapshotAnalysisEngine` while pre-v0.8 interfaces are
  removed in later interface tasks.
- `technical` owns deterministic RSI/MACD/Bollinger/MA/volume scoring.
- Missing or invalid inputs raise an execution error; they do not produce a neutral score.
- VMD is context only and remains absent from the weighted production registry.
- Verdict will consume consensus in Task 13 and is not registered as an engine.

## Verification

Registry duplication/missing-name behavior, declared capabilities, typed scoring and insufficient
history failure are covered by focused unit tests.
