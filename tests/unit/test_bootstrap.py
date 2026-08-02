"""Composition-root construction and injection tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from src.diting.bootstrap import (
    ApplicationDependencies,
    bootstrap_application,
    bootstrap_runtime,
    create_container,
)
from src.diting.config import AppConfig
from src.diting.infra.config_loader import ConfigLoader


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 2, tzinfo=UTC)

    def today(self) -> date:
        return date(2026, 8, 2)

    def monotonic(self) -> float:
        return 7.0


class FakeResource:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


def test_fake_container_uses_only_injected_dependencies() -> None:
    clock = FakeClock()
    gateway = FakeResource()
    container = create_container(
        AppConfig(),
        ApplicationDependencies(clock=clock, data_gateway=gateway),
    )

    assert container.clock is clock
    assert container.data_gateway is gateway
    assert container.cache_store is None
    assert container.settings.runtime.public_readonly is False


def test_bootstrap_reads_config_once_and_registers_snapshot(tmp_path: Path) -> None:
    config_path = tmp_path / "diting.yaml"
    config_path.write_text(
        "runtime:\n  environment: test\npipeline:\n  max_workers: 3\n",
        encoding="utf-8",
    )
    before = {item.name for item in tmp_path.iterdir()}

    container = bootstrap_application(config_path, environ={})
    try:
        assert container.settings.runtime.environment == "test"
        assert container.settings.pipeline.max_workers == 3
        assert ConfigLoader.current() is container.settings
        assert {item.name for item in tmp_path.iterdir()} == before
    finally:
        ConfigLoader.reset()


def test_missing_config_and_fakes_do_not_write_files(tmp_path: Path) -> None:
    container = bootstrap_application(
        tmp_path / "missing.yaml",
        environ={},
        dependencies=ApplicationDependencies(clock=FakeClock(), data_gateway=FakeResource()),
    )
    try:
        assert list(tmp_path.iterdir()) == []
        assert container.settings == AppConfig()
    finally:
        ConfigLoader.reset()


def test_container_closes_a_shared_resource_once() -> None:
    resource = FakeResource()
    container = create_container(
        AppConfig(),
        ApplicationDependencies(
            clock=FakeClock(),
            data_gateway=resource,
            cache_store=resource,
            durable_store=resource,
        ),
    )

    container.close()
    assert resource.close_count == 1


def test_runtime_bootstrap_migrates_and_builds_gateway(tmp_path: Path) -> None:
    config_path = tmp_path / "diting.yaml"
    business = tmp_path / "diting.db"
    cache = tmp_path / "diting_cache.db"
    config_path.write_text(
        "database:\n"
        f"  business_path: {business.as_posix()}\n"
        f"  cache_path: {cache.as_posix()}\n"
        "providers: []\n",
        encoding="utf-8",
    )

    container = bootstrap_runtime(config_path, environ={})
    try:
        assert business.exists()
        assert cache.exists()
        assert container.data_gateway is not None
        assert container.cache_store is not None
        assert container.durable_store is not None
        assert container.analysis is not None
        assert container.jobs is not None
        assert container.report is not None
    finally:
        container.close()
        ConfigLoader.reset()
