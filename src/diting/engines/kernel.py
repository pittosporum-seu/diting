"""Explicit v0.8 engine contracts and registry without import side effects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from types import MappingProxyType

from ..enums import EngineMode
from ..schema import DataSnapshot, EngineCapabilities, EngineContext, EngineResult


class SnapshotAnalysisEngine(ABC):
    """Analysis engine that consumes the frozen snapshot used by the whole run."""

    name: str
    version: str
    mode: EngineMode

    @abstractmethod
    def capabilities(self) -> EngineCapabilities:
        """Declare data, dependency and execution requirements."""

    @abstractmethod
    def analyze(self, snapshot: DataSnapshot, context: EngineContext) -> EngineResult:
        """Return a validated result or raise a typed execution error."""


class EngineRegistry:
    """Immutable explicit engine catalog assembled by the composition root."""

    def __init__(self, engines: Iterable[SnapshotAnalysisEngine]) -> None:
        catalog: dict[str, SnapshotAnalysisEngine] = {}
        for engine in engines:
            if not engine.name or engine.name in catalog:
                raise ValueError(f"duplicate or empty engine name: {engine.name!r}")
            catalog[engine.name] = engine
        self._catalog = MappingProxyType(catalog)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._catalog)

    def get(self, name: str) -> SnapshotAnalysisEngine | None:
        return self._catalog.get(name)

    def require(self, name: str) -> SnapshotAnalysisEngine:
        engine = self.get(name)
        if engine is None:
            raise KeyError(f"engine is not registered: {name}")
        return engine
