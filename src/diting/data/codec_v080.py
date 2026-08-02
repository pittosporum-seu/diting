"""Schema-versioned compressed JSON codec for normalized gateway payloads."""

from __future__ import annotations

import json
import zlib
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from typing import Any

from ..enums import DataSource
from ..schema import (
    Financials,
    FundFlow,
    HistoricalBar,
    HistoricalSeries,
    Instrument,
    InstrumentPage,
    RealtimeQuote,
    TradingCalendar,
    TradingSession,
)

SCHEMA_VERSIONS = {
    "quote": "quote-v1",
    "historical": "bars-v1",
    "financials": "financials-v1",
    "fund_flow": "fund-flow-v1",
    "instrument_page": "instruments-v1",
    "trading_calendar": "calendar-v1",
}


def encode_payload(value: Any) -> bytes:
    raw = json.dumps(
        asdict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode()
    return zlib.compress(raw, level=6)


def decode_payload(data_type: str, payload: bytes) -> Any:
    raw = json.loads(zlib.decompress(payload).decode())
    decoders = {
        "quote": _quote,
        "historical": _historical,
        "financials": _financials,
        "fund_flow": _fund_flow,
        "instrument_page": _instrument_page,
        "trading_calendar": _trading_calendar,
    }
    try:
        decoder = decoders[data_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported cache data type: {data_type}") from exc
    return decoder(raw)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime, Enum)):
        return value.value if isinstance(value, Enum) else value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _source(value: str | None) -> DataSource:
    try:
        return DataSource(value or "unknown")
    except ValueError:
        return DataSource.UNKNOWN


def _quote(raw: dict[str, Any]) -> RealtimeQuote:
    raw["timestamp"] = datetime.fromisoformat(raw["timestamp"])
    raw["source"] = _source(raw.get("source"))
    return RealtimeQuote(**raw)


def _historical(raw: dict[str, Any]) -> HistoricalSeries:
    bars = tuple(
        HistoricalBar(
            trading_date=date.fromisoformat(item["trading_date"]),
            open=item["open"],
            high=item["high"],
            low=item["low"],
            close=item["close"],
            volume=item["volume"],
            turnover=item.get("turnover"),
        )
        for item in raw["bars"]
    )
    return HistoricalSeries(
        symbol=raw["symbol"],
        bars=bars,
        period=raw["period"],
        adjustment=raw["adjustment"],
        schema_version=raw["schema_version"],
    )


def _financials(raw: dict[str, Any]) -> Financials:
    raw["report_date"] = date.fromisoformat(raw["report_date"])
    raw["source"] = _source(raw.get("source"))
    return Financials(**raw)


def _fund_flow(raw: dict[str, Any]) -> FundFlow:
    raw["date"] = date.fromisoformat(raw["date"])
    return FundFlow(**raw)


def _instrument_page(raw: dict[str, Any]) -> InstrumentPage:
    items = []
    for item in raw["items"]:
        for key in ("listed_on", "delisted_on"):
            if item.get(key):
                item[key] = date.fromisoformat(item[key])
        items.append(Instrument(**item))
    return InstrumentPage(
        items=tuple(items),
        total=raw["total"],
        next_cursor=raw.get("next_cursor"),
    )


def _trading_calendar(raw: dict[str, Any]) -> TradingCalendar:
    sessions = []
    for item in raw["sessions"]:
        item["trading_date"] = date.fromisoformat(item["trading_date"])
        for key in ("open_at", "close_at"):
            if item.get(key):
                item[key] = datetime.fromisoformat(item[key])
        sessions.append(TradingSession(**item))
    return TradingCalendar(
        market=raw["market"],
        sessions=tuple(sessions),
        timezone=raw["timezone"],
    )
