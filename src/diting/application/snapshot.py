"""Build immutable, traceable data snapshots for analysis runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from ..enums import FetchMode
from ..ports import Clock, DataGateway
from ..schema import (
    AnalysisRequest,
    DataResult,
    DataSnapshot,
    DataWarning,
    FinancialRequest,
    FundFlowRequest,
    HistoricalRequest,
    QuoteRequest,
)

_SYMBOL_PATTERN = re.compile(r"^(?:sh|sz|bj)?(\d{6})$", re.IGNORECASE)


class DataSnapshotBuilder:
    """Read one logical market-data snapshot through the only data gateway."""

    def __init__(
        self,
        gateway: DataGateway,
        clock: Clock,
        *,
        history_days: int = 400,
    ) -> None:
        if history_days < 60:
            raise ValueError("history_days must be at least 60")
        self._gateway = gateway
        self._clock = clock
        self._history_days = history_days

    def build(self, request: AnalysisRequest) -> DataSnapshot:
        symbol = self.normalize_symbol(request.symbol)
        created_at = self._clock.now()
        as_of = request.as_of or created_at
        mode = FetchMode.FRESH_REQUIRED

        quote = self._gateway.get_quotes(
            QuoteRequest(
                symbols=(symbol,),
                mode=mode,
                force_refresh=request.force_refresh,
                deadline=request.deadline,
            )
        ).get(symbol)
        if quote is None:
            quote = DataResult(
                data=None,
                data_time=None,
                warnings=(
                    DataWarning(
                        code="QUOTE_RESULT_MISSING",
                        message=f"行情网关未返回 {symbol}",
                    ),
                ),
                error_code="QUOTE_RESULT_MISSING",
            )

        historical = self._gateway.get_historical(
            HistoricalRequest(
                symbol=symbol,
                start_date=as_of.date() - timedelta(days=self._history_days),
                end_date=as_of.date(),
                mode=mode,
                force_refresh=request.force_refresh,
                deadline=request.deadline,
            )
        )
        financials = self._gateway.get_financials(
            FinancialRequest(
                symbol=symbol,
                as_of=as_of.date(),
                mode=mode,
                force_refresh=request.force_refresh,
                deadline=request.deadline,
            )
        )
        fund_flow = self._gateway.get_fund_flow(
            FundFlowRequest(
                symbol=symbol,
                trading_date=as_of.date(),
                mode=mode,
                force_refresh=request.force_refresh,
                deadline=request.deadline,
            )
        )

        results = (quote, historical, financials, fund_flow)
        warnings = tuple(warning for result in results for warning in result.warnings)
        traces = tuple(trace for result in results for trace in result.provider_traces)
        completeness = sum(result.succeeded for result in results) / len(results)
        payload = {
            "symbol": symbol,
            "as_of": as_of,
            "quote": self._result_identity(quote),
            "historical": self._result_identity(historical),
            "financials": self._result_identity(financials),
            "fund_flow": self._result_identity(fund_flow),
        }
        snapshot_hash = hashlib.sha256(self._canonical_json(payload)).hexdigest()

        return DataSnapshot(
            snapshot_id=f"snap_{snapshot_hash[:24]}",
            symbol=symbol,
            created_at=created_at,
            as_of=as_of,
            quote=quote,
            historical=historical,
            financials=financials,
            fund_flow=fund_flow,
            provider_traces=traces,
            completeness=round(completeness, 4),
            snapshot_hash=snapshot_hash,
            warnings=warnings,
        )

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        candidate = symbol.strip().lower().replace(".", "")
        match = _SYMBOL_PATTERN.fullmatch(candidate)
        if match is None:
            raise ValueError("symbol must be a six-digit A-share code")
        return match.group(1)

    @classmethod
    def _result_identity(cls, result: DataResult[Any]) -> dict[str, Any]:
        """Keep business data identity while excluding cache and retry noise."""

        return {
            "data": result.data,
            "data_time": result.data_time,
            "request_hash": result.request_hash,
            "error_code": result.error_code,
        }

    @classmethod
    def _canonical_json(cls, value: Any) -> bytes:
        return json.dumps(
            value,
            default=cls._json_default,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _json_default(value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, tuple):
            return list(value)
        raise TypeError(f"unsupported snapshot value: {type(value).__name__}")
