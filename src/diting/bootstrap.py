"""The single v0.8 composition root for configuration and external dependencies."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import AppConfig, Config, load_app_config
from .infra.config_loader import ConfigLoader
from .infra.logging_config import get_logger
from .ports import (
    CacheStore,
    Clock,
    DataGateway,
    DurableStore,
    LLMPort,
    Notifier,
    ReportPort,
    SandboxPort,
)

logger = get_logger(__name__)


class SystemClock:
    """Production clock using the A-share market timezone."""

    def __init__(self, timezone: str = "Asia/Shanghai") -> None:
        self._timezone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(self._timezone)

    def today(self) -> date:
        return self.now().date()

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True)
class ApplicationDependencies:
    """Injected adapters used to assemble an application container."""

    clock: Clock | None = None
    data_gateway: DataGateway | None = None
    cache_store: CacheStore | None = None
    durable_store: DurableStore | None = None
    llm: LLMPort | None = None
    sandbox: SandboxPort | None = None
    report: ReportPort | None = None
    notifier: Notifier | None = None
    legacy_repository: Any | None = None


@dataclass(frozen=True)
class ApplicationContainer:
    """Immutable dependency graph shared by CLI, HTTP, workers and Python API."""

    settings: AppConfig
    clock: Clock
    data_gateway: DataGateway | None = None
    cache_store: CacheStore | None = None
    durable_store: DurableStore | None = None
    llm: LLMPort | None = None
    sandbox: SandboxPort | None = None
    report: ReportPort | None = None
    notifier: Notifier | None = None
    legacy_repository: Any | None = None

    def close(self) -> None:
        """Close each injected resource at most once."""

        seen: set[int] = set()
        for resource in (
            self.data_gateway,
            self.cache_store,
            self.durable_store,
            self.llm,
            self.sandbox,
            self.report,
            self.notifier,
            self.legacy_repository,
        ):
            if resource is None or id(resource) in seen:
                continue
            seen.add(id(resource))
            close = getattr(resource, "close", None)
            if callable(close):
                close()


def create_container(
    settings: AppConfig,
    dependencies: ApplicationDependencies | None = None,
) -> ApplicationContainer:
    """Assemble an immutable container without reading raw configuration."""

    deps = dependencies or ApplicationDependencies()
    return ApplicationContainer(
        settings=settings,
        clock=deps.clock or SystemClock(),
        data_gateway=deps.data_gateway,
        cache_store=deps.cache_store,
        durable_store=deps.durable_store,
        llm=deps.llm,
        sandbox=deps.sandbox,
        report=deps.report,
        notifier=deps.notifier,
        legacy_repository=deps.legacy_repository,
    )


def bootstrap_application(
    config_path: Path | str | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    dependencies: ApplicationDependencies | None = None,
) -> ApplicationContainer:
    """Read, validate and register configuration, then assemble dependencies."""

    settings = load_app_config(config_path, overrides=overrides, environ=environ)
    ConfigLoader.configure(settings)
    return create_container(settings, dependencies)


def bootstrap_runtime(
    config_path: Path | str | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> ApplicationContainer:
    """Build the production data runtime after validating and migrating both databases."""

    settings = load_app_config(config_path, overrides=overrides, environ=environ)
    ConfigLoader.configure(settings)
    clock = SystemClock()
    dependencies = build_data_dependencies(settings, clock)
    return create_container(settings, dependencies)


def build_data_dependencies(settings: AppConfig, clock: Clock) -> ApplicationDependencies:
    """Construct the sole cache and market-data path used by runtime interfaces."""

    from .cache.store_v080 import MemoryCacheStore, SQLiteCacheStore, TieredCacheStore
    from .data.calendar_v080 import ExchangeCalendarState
    from .data.gateway_v080 import CachedMarketDataGateway
    from .data.legacy_adapter_v080 import LegacyProviderAdapter
    from .data.providers.akshare import AkShareProvider
    from .data.providers.base import DataProvider
    from .persistence.migrations import migrate_databases

    business_path = settings.database.business_path
    cache_path = settings.database.cache_path
    backup_dir = business_path.parent / "backups" / "v080"
    reports = migrate_databases(
        business_path,
        cache_path,
        backup_dir=backup_dir,
    )
    if not all(report.ready for report in reports):
        from .infra.errors import MigrationError

        raise MigrationError("runtime", "database readiness check failed")

    providers = []
    config = Config(settings=settings)
    for provider_config in sorted(settings.providers, key=lambda item: item.priority):
        if provider_config.requires_key and not config.get(provider_config.requires_key):
            continue
        provider_settings = provider_config.settings.model_dump(mode="python")
        try:
            if provider_config.name == "mx_data":
                from .data.providers.mx_data import MxDataProvider

                provider = MxDataProvider(api_key=config.get("MX_APIKEY"))
            else:
                provider = DataProvider.from_config(provider_config.name, provider_settings)
            if provider_config.auto_detect and not provider.health_check():
                continue
            providers.append(
                LegacyProviderAdapter(
                    provider,
                    max_batch_size=provider_config.settings.max_batch,
                )
            )
        except Exception as exc:
            logger.warning(
                "provider.import_failed",
                provider=provider_config.name,
                reason=type(exc).__name__,
            )

    if not providers:
        providers.append(LegacyProviderAdapter(AkShareProvider()))

    memory = MemoryCacheStore(clock, max_size=settings.pipeline.cache.max_size)
    persistent = SQLiteCacheStore(cache_path, clock)
    cache = TieredCacheStore(memory, persistent)
    calendar = ExchangeCalendarState()
    gateway = CachedMarketDataGateway(tuple(providers), cache, clock, calendar=calendar)
    return ApplicationDependencies(
        clock=clock,
        data_gateway=gateway,
        cache_store=cache,
    )


def build_legacy_repository(settings: AppConfig):
    """Build the legacy provider chain during migration; remove after Task 09."""

    from .data.providers.akshare import AkShareProvider
    from .data.providers.base import DataProvider
    from .data.repository import MarketDataRepository

    config = Config(settings=settings)
    providers = []
    for provider_config in settings.providers:
        if provider_config.requires_key and not config.get(provider_config.requires_key):
            continue
        provider_settings = provider_config.settings.model_dump(mode="python")
        try:
            provider = DataProvider.from_config(provider_config.name, provider_settings)
            if provider_config.auto_detect and not provider.health_check():
                continue
            providers.append(provider)
        except Exception as exc:
            logger.warning(
                "provider.import_failed",
                provider=provider_config.name,
                reason=type(exc).__name__,
            )

    if not providers:
        providers.append(AkShareProvider())
    return MarketDataRepository(providers=providers)


def build_mx_repository(api_key: str):
    """Build the one-provider repository used by the legacy init connectivity check."""

    from .data.providers.mx_data import MxDataProvider
    from .data.repository import MarketDataRepository

    return MarketDataRepository(providers=[MxDataProvider(api_key=api_key)])
