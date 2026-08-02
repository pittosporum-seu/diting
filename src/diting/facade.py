"""Stable Python facade over the v0.8 composition root and application ports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Self
from uuid import uuid4

from .enums import AnalysisProfile, FetchMode, RunStatus
from .schema import (
    AnalysisRequest,
    AnalysisRun,
    DataResult,
    DataWarning,
    QuoteRequest,
    RealtimeQuote,
    ScanResult,
)

if TYPE_CHECKING:
    from .bootstrap import ApplicationContainer


class Diting:
    """Synchronous public API that owns one immutable application container."""

    def __init__(self, container: ApplicationContainer) -> None:
        self._container = container
        self._lock = RLock()
        self._closed = False

    @classmethod
    def from_config(
        cls,
        path: Path | str | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> Self:
        """Build a complete runtime from strict YAML/environment/override configuration."""

        from .bootstrap import bootstrap_runtime

        return cls(bootstrap_runtime(path, overrides=overrides))

    @property
    def settings(self):
        """Return the immutable validated configuration snapshot."""

        self._ensure_open()
        return self._container.settings

    def get_quote(
        self,
        symbol: str,
        freshness: FetchMode | str = FetchMode.CACHE_PREFERRED,
        *,
        force_refresh: bool = False,
    ) -> DataResult[RealtimeQuote]:
        """Read one normalized quote through the cached market-data gateway."""

        self._ensure_open()
        normalized = _symbol(symbol)
        mode = _fetch_mode(freshness)
        gateway = self._container.data_gateway
        if gateway is None:
            raise RuntimeError("Diting DataGateway is not configured")
        result = gateway.get_quotes(
            QuoteRequest(
                symbols=(normalized,),
                mode=mode,
                force_refresh=force_refresh,
            )
        ).get(normalized)
        if result is not None:
            return result
        return DataResult(
            data=None,
            data_time=None,
            request_hash="",
            error_code="DATA_UNAVAILABLE",
            warnings=(
                DataWarning(
                    code="DATA_UNAVAILABLE",
                    message=f"quote result missing for {normalized}",
                    recoverable=True,
                ),
            ),
        )

    def analyze(
        self,
        symbol: str,
        profile: AnalysisProfile | str = AnalysisProfile.STANDARD,
        *,
        force_refresh: bool = False,
        engines: Sequence[str] | None = None,
    ) -> AnalysisRun:
        """Run the shared synchronous analysis orchestrator for one security."""

        self._ensure_open()
        orchestrator = self._container.analysis
        if orchestrator is None:
            raise RuntimeError("Diting AnalysisOrchestrator is not configured")
        requested_engines = tuple(engines) if engines is not None else None
        return orchestrator.analyze(
            AnalysisRequest(
                symbol=_symbol(symbol),
                profile=_analysis_profile(profile),
                force_refresh=force_refresh,
                requested_engines=requested_engines,
                request_id=f"py_{uuid4().hex}",
            )
        )

    def scan(self, limit: int = 20) -> ScanResult:
        """Run the active production opportunity strategy or return typed unavailability."""

        self._ensure_open()
        if not 1 <= limit <= 100:
            raise ValueError("scan limit must be between 1 and 100")
        store = self._container.durable_store
        if store is None:
            raise RuntimeError("Diting DurableStore is not configured")
        selected = self._container.settings.strategy.selected
        active = store.get_active_strategy(selected)
        if active is None:
            return _unavailable_scan(
                self._container,
                error_code="NO_ACTIVE_STRATEGY",
                message="no active production opportunity strategy",
            )
        if self._container.scanner is None:
            return _unavailable_scan(
                self._container,
                error_code="SCAN_SERVICE_UNAVAILABLE",
                message="active-strategy scan orchestrator is not configured",
                strategy_version=f"{active.name}:{active.version}",
            )
        return self._container.scanner.scan(limit=limit)

    def close(self) -> None:
        """Release owned workers, adapters and stores exactly once."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._container.close()

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def _ensure_open(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Diting client is closed")


def _symbol(symbol: str) -> str:
    normalized = symbol.strip()
    if len(normalized) != 6 or not normalized.isdigit():
        raise ValueError("symbol must contain exactly six digits")
    return normalized


def _fetch_mode(mode: FetchMode | str) -> FetchMode:
    if isinstance(mode, FetchMode):
        return mode
    try:
        return FetchMode(mode)
    except ValueError:
        allowed = ", ".join(item.value for item in FetchMode)
        raise ValueError(f"freshness must be one of: {allowed}") from None


def _analysis_profile(profile: AnalysisProfile | str) -> AnalysisProfile:
    if isinstance(profile, AnalysisProfile):
        return profile
    try:
        return AnalysisProfile(profile)
    except ValueError:
        raise ValueError("profile must be 'standard' or 'deep'") from None


def _unavailable_scan(
    container: ApplicationContainer,
    *,
    error_code: str,
    message: str,
    strategy_version: str | None = None,
) -> ScanResult:
    return ScanResult(
        scan_id=f"scan_{uuid4().hex}",
        status=RunStatus.FAILED,
        strategy_version=strategy_version,
        data_date=container.clock.today(),
        warnings=(DataWarning(code=error_code, message=message, recoverable=True),),
        error_code=error_code,
    )
