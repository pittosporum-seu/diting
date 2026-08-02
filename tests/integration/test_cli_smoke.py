"""v0.8 breaking CLI contract tests without provider/network access."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from src.diting import __version__
from src.diting.config import AppConfig
from src.diting.enums import DataSource, RunStatus, StrategyState
from src.diting.facade import Diting
from src.diting.main import cli
from src.diting.schema import (
    AnalysisRequest,
    AnalysisRun,
    DataResult,
    RealtimeQuote,
    ScanResult,
    StrategyVersion,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)


class FakeClock:
    def now(self):
        return NOW

    def today(self):
        return NOW.date()


class FakeStore:
    def __init__(self) -> None:
        self.watchlist = {}
        self.audits = []
        self.active = StrategyVersion(
            "mean_reversion_v1",
            "1.0",
            StrategyState.ACTIVE,
            "manifest-hash",
            NOW,
            NOW,
        )

    def list_watchlist(self, _owner_id):
        return tuple(self.watchlist.values())

    def upsert_watchlist(self, entry):
        self.watchlist[entry.symbol] = entry

    def delete_watchlist(self, _owner_id, symbol):
        return self.watchlist.pop(symbol, None) is not None

    def append_audit(self, event):
        self.audits.append(event)

    def get_active_strategy(self, _name):
        return self.active


class FakeDiting:
    def __init__(self) -> None:
        self.store = FakeStore()
        self._container = SimpleNamespace(
            durable_store=self.store,
            clock=FakeClock(),
            settings=AppConfig(),
        )
        self.analysis_calls = []
        self.quote_calls = []
        self.scan_limits = []
        self.close_count = 0

    def get_quote(self, symbol, freshness="cache_preferred", *, force_refresh=False):
        self.quote_calls.append((symbol, freshness, force_refresh))
        quote = RealtimeQuote(
            symbol=symbol.strip(),
            name=f"股票{symbol.strip()}",
            price=42,
            change_pct=1.5,
            open=41,
            high=43,
            low=40,
            volume=100,
            turnover=4200,
            pe=20,
            pb=3,
            timestamp=NOW,
            source=DataSource.AKSHARE,
        )
        return DataResult(data=quote, data_time=NOW, request_hash="quote")

    def analyze(self, symbol, profile="standard", *, force_refresh=False, engines=None):
        self.analysis_calls.append((symbol, profile, force_refresh, engines))
        request = AnalysisRequest(symbol, request_id="cli-test")
        if profile == "deep":
            from src.diting.enums import AnalysisProfile

            request = replace(request, profile=AnalysisProfile.DEEP)
        return AnalysisRun(
            run_id="run_cli",
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

    def scan(self, limit=20):
        self.scan_limits.append(limit)
        return ScanResult("scan_cli", RunStatus.SUCCEEDED, "mean_reversion_v1:1.0", NOW.date())

    def close(self):
        self.close_count += 1


@pytest.fixture
def cli_runtime(monkeypatch):
    fake = FakeDiting()
    monkeypatch.setattr(
        Diting,
        "from_config",
        classmethod(lambda _cls, _path=None, _overrides=None: fake),
    )
    return CliRunner(), fake


def test_help_version_and_empty_invocation() -> None:
    runner = CliRunner()

    help_result = runner.invoke(cli, ["--help"])
    version_result = runner.invoke(cli, ["--version"])
    empty_result = runner.invoke(cli, [])

    assert help_result.exit_code == 0
    assert all(name in help_result.output for name in ("analyze", "quote", "scan", "strategy"))
    assert version_result.exit_code == 0
    assert __version__ in version_result.output
    assert empty_result.exit_code == 0
    assert "谛听" in empty_result.output


def test_code_shorthand_maps_only_to_standard_analysis(cli_runtime) -> None:
    runner, fake = cli_runtime
    result = runner.invoke(cli, ["002475"])

    assert result.exit_code == 0
    assert "run_cli" in result.output
    assert fake.analysis_calls == [("002475", "standard", False, None)]
    assert fake.close_count == 1


def test_explicit_deep_analysis_propagates_options_and_json(cli_runtime) -> None:
    runner, fake = cli_runtime
    result = runner.invoke(
        cli,
        [
            "analyze",
            "002475",
            "--profile",
            "deep",
            "--force-refresh",
            "--engine",
            "technical",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"run_id": "run_cli"' in result.output
    assert fake.analysis_calls == [("002475", "deep", True, ("technical",))]


def test_quote_uses_freshness_contract(cli_runtime) -> None:
    runner, fake = cli_runtime
    result = runner.invoke(
        cli,
        ["quote", "002475", "--freshness", "fresh_required", "--force-refresh", "--json"],
    )

    assert result.exit_code == 0
    assert '"request_hash": "quote"' in result.output
    assert fake.quote_calls == [("002475", "fresh_required", True)]


def test_compare_requires_two_symbols_and_uses_quote_only(cli_runtime) -> None:
    runner, fake = cli_runtime
    invalid = runner.invoke(cli, ["compare", "002475"])
    compared = runner.invoke(cli, ["compare", "002475,600519", "--json"])

    assert invalid.exit_code == 2
    assert "between 2 and 20" in invalid.output
    assert compared.exit_code == 0
    assert '"symbol": "600519"' in compared.output
    assert [item[0] for item in fake.quote_calls] == ["002475", "600519"]


def test_scan_uses_active_strategy_facade(cli_runtime) -> None:
    runner, fake = cli_runtime
    result = runner.invoke(cli, ["scan", "--limit", "5", "--json"])

    assert result.exit_code == 0
    assert '"scan_id": "scan_cli"' in result.output
    assert fake.scan_limits == [5]


def test_watchlist_crud_is_typed_persistent_and_audited(cli_runtime) -> None:
    runner, fake = cli_runtime
    added = runner.invoke(
        cli,
        ["watchlist", "--add", "002475", "--name", "立讯精密", "--tag", "核心"],
    )
    listed = runner.invoke(cli, ["watchlist", "--json"])
    removed = runner.invoke(cli, ["watchlist", "--remove", "002475"])

    assert added.exit_code == listed.exit_code == removed.exit_code == 0
    assert '"symbol": "002475"' in listed.output
    assert [event.action for event in fake.store.audits] == [
        "watchlist.upsert",
        "watchlist.delete",
    ]
    assert "自选列表为空" in removed.output


def test_strategy_reports_active_registry_state(cli_runtime) -> None:
    runner, _ = cli_runtime
    result = runner.invoke(cli, ["strategy", "--json"])

    assert result.exit_code == 0
    assert '"active": true' in result.output
    assert '"manifest_hash": "manifest-hash"' in result.output


@pytest.mark.parametrize("command", ("l0", "l1", "l2", "run", "init"))
def test_removed_commands_fail_clearly(command: str) -> None:
    result = CliRunner().invoke(cli, [command])

    assert result.exit_code == 2
    assert "CLI_COMMAND_REMOVED" in result.output


def test_serve_help_does_not_boot_runtime() -> None:
    result = CliRunner().invoke(cli, ["serve", "--help"])

    assert result.exit_code == 0
    assert "单 worker" in result.output
