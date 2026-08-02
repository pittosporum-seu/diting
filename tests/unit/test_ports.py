"""Dependency-port isolation and structural-typing tests."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, date, datetime

from src.diting.ports import Clock, DataGateway


class FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 2, tzinfo=UTC)

    def today(self) -> date:
        return date(2026, 8, 2)

    def monotonic(self) -> float:
        return 1.0


class FakeGateway:
    def get_quotes(self, request):
        return {}

    def get_historical(self, request):
        raise NotImplementedError

    def get_financials(self, request):
        raise NotImplementedError

    def get_fund_flow(self, request):
        raise NotImplementedError

    def search_instruments(self, request):
        raise NotImplementedError

    def get_trading_calendar(self, request):
        raise NotImplementedError


def test_ports_are_runtime_checkable() -> None:
    assert isinstance(FakeClock(), Clock)
    assert isinstance(FakeGateway(), DataGateway)


def test_importing_ports_has_no_optional_or_adapter_imports() -> None:
    command = (
        "import sys; import src.diting.ports; "
        "blocked=('akshare','litellm','fastapi','src.diting.data.providers'); "
        "print(','.join(name for name in blocked if name in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""
