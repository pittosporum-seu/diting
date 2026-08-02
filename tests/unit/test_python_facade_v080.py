"""Stable v0.8 Python facade lifecycle and port-parity tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import src.diting.bootstrap as bootstrap_module
from src.diting import (
    AnalysisProfile,
    AnalysisRun,
    DataResult,
    Diting,
    FetchMode,
    RealtimeQuote,
    ScanResult,
)
from src.diting.bootstrap import ApplicationDependencies, create_container
from src.diting.config import AppConfig
from src.diting.enums import DataSource, RunStatus, StrategyState
from src.diting.schema import AnalysisRequest, StrategyVersion

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return NOW

    def today(self) -> date:
        return NOW.date()

    def monotonic(self) -> float:
        return 1.0


class FakeGateway:
    def __init__(self) -> None:
        self.requests = []
        self.close_count = 0

    def get_quotes(self, request):
        self.requests.append(request)
        quote = RealtimeQuote(
            symbol=request.symbols[0],
            name="立讯精密",
            price=42,
            change_pct=1.5,
            open=41,
            high=43,
            low=40,
            volume=100,
            turnover=4200,
            timestamp=NOW,
            source=DataSource.AKSHARE,
        )
        return {
            quote.symbol: DataResult(
                data=quote,
                data_time=NOW,
                request_hash="quote-hash",
            )
        }

    def close(self) -> None:
        self.close_count += 1


class FakeAnalysis:
    def __init__(self) -> None:
        self.requests: list[AnalysisRequest] = []

    def analyze(self, request):
        self.requests.append(request)
        return AnalysisRun(
            run_id="run_python",
            request=request,
            status=RunStatus.SUCCEEDED,
            snapshot_id="snapshot",
            snapshot_hash="snapshot-hash",
            config_hash="config-hash",
            strategy_version="analysis-v1",
            code_version="0.8.0",
            started_at=NOW,
            completed_at=NOW,
        )


class FakeStore:
    def __init__(self, active=None) -> None:
        self.active = active

    def get_active_strategy(self, _name):
        return self.active


class FakeScanner:
    def __init__(self) -> None:
        self.limits = []

    def scan(self, *, limit=20):
        self.limits.append(limit)
        return ScanResult("scan_active", RunStatus.SUCCEEDED, "mean_reversion_v1:1.0", NOW.date())


def _container(*, active=None, scanner=None):
    gateway = FakeGateway()
    analysis = FakeAnalysis()
    store = FakeStore(active)
    container = create_container(
        AppConfig(),
        ApplicationDependencies(
            clock=FakeClock(),
            data_gateway=gateway,
            durable_store=store,
            analysis=analysis,
            scanner=scanner,
        ),
    )
    return container, gateway, analysis


def test_from_config_forwards_path_and_overrides(monkeypatch, tmp_path: Path) -> None:
    container, _, _ = _container()
    calls = []

    def fake_bootstrap(path=None, *, overrides=None):
        calls.append((path, overrides))
        return container

    monkeypatch.setattr(bootstrap_module, "bootstrap_runtime", fake_bootstrap)
    config_path = tmp_path / "diting.yaml"
    client = Diting.from_config(config_path, overrides={"runtime": {"environment": "test"}})
    try:
        assert calls == [(config_path, {"runtime": {"environment": "test"}})]
        assert client.settings is container.settings
    finally:
        client.close()


def test_quote_and_analysis_use_injected_gateway_and_orchestrator() -> None:
    container, gateway, analysis = _container()
    client = Diting(container)
    try:
        quote = client.get_quote(" 002475 ", freshness="fresh_required", force_refresh=True)
        run = client.analyze("002475", profile="deep", force_refresh=True, engines=("technical",))

        assert quote.data.symbol == "002475"
        assert gateway.requests[0].mode is FetchMode.FRESH_REQUIRED
        assert gateway.requests[0].force_refresh is True
        assert run.run_id == "run_python"
        assert analysis.requests[0].profile is AnalysisProfile.DEEP
        assert analysis.requests[0].requested_engines == ("technical",)
        assert analysis.requests[0].request_id.startswith("py_")
    finally:
        client.close()


def test_scan_never_falls_back_without_active_strategy() -> None:
    container, _, _ = _container()
    with Diting(container) as client:
        result = client.scan()

    assert result.status is RunStatus.FAILED
    assert result.error_code == "NO_ACTIVE_STRATEGY"
    assert result.items == ()
    assert result.warnings[0].code == "NO_ACTIVE_STRATEGY"


def test_scan_uses_injected_active_strategy_orchestrator() -> None:
    active = StrategyVersion(
        name="mean_reversion_v1",
        version="1.0",
        state=StrategyState.ACTIVE,
        manifest_hash="manifest",
        created_at=NOW,
        activated_at=NOW,
    )
    scanner = FakeScanner()
    container, _, _ = _container(active=active, scanner=scanner)
    with Diting(container) as client:
        result = client.scan(limit=5)

    assert result.scan_id == "scan_active"
    assert scanner.limits == [5]


def test_context_manager_closes_once_and_rejects_future_use() -> None:
    container, gateway, _ = _container()
    with Diting(container) as client:
        assert client.get_quote("002475").succeeded
    client.close()

    assert gateway.close_count == 1
    with pytest.raises(RuntimeError, match="closed"):
        client.get_quote("002475")


@pytest.mark.parametrize("symbol", ("", "2475", "ABCDEF", "1234567"))
def test_symbol_validation_is_stable(symbol: str) -> None:
    container, _, _ = _container()
    client = Diting(container)
    try:
        with pytest.raises(ValueError, match="six digits"):
            client.get_quote(symbol)
    finally:
        client.close()


def test_public_exports_are_intentional() -> None:
    assert Diting.__module__ == "src.diting.facade"
    assert DataResult.__name__ == "DataResult"
    assert RealtimeQuote.__name__ == "RealtimeQuote"
    assert AnalysisRun.__name__ == "AnalysisRun"
    assert ScanResult.__name__ == "ScanResult"
