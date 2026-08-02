"""Strict structured-output engine boundary tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from src.diting.engines.structured_v080 import StructuredWyckoffEngine
from src.diting.infra.errors import StructuredOutputError
from src.diting.schema import (
    DataResult,
    DataSnapshot,
    EngineContext,
    HistoricalBar,
    HistoricalSeries,
    LLMResponse,
    RealtimeQuote,
)

NOW = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
CONTEXT = EngineContext(
    deadline=NOW + timedelta(seconds=15),
    config_hash="config",
    strategy_version="analysis-v1",
    prompt_version="v080-1",
    model="fake-model",
)


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(content=self.content, model=request.model, request_id="llm-1")


def _snapshot() -> DataSnapshot:
    bars = tuple(
        HistoricalBar(
            date(2026, 1, 1) + timedelta(days=index),
            20 + index / 10,
            21 + index / 10,
            19 + index / 10,
            20 + index / 10,
            1000 + index,
        )
        for index in range(80)
    )
    quote = RealtimeQuote("002475", "立讯精密", 42, 1, 41, 43, 40, 100, 4200, timestamp=NOW)
    return DataSnapshot(
        snapshot_id="snapshot",
        symbol="002475",
        created_at=NOW,
        as_of=NOW,
        quote=DataResult(data=quote, data_time=NOW),
        historical=DataResult(
            data=HistoricalSeries(symbol="002475", bars=bars),
            data_time=NOW,
        ),
        snapshot_hash="hash",
    )


def _valid_output() -> dict:
    return {
        "engine_score": 72.0,
        "confidence": 0.8,
        "narrative": "价格放量进入吸筹后段。",
        "evidence": [{"code": "PHASE_D", "summary": "接近区间上沿", "value": 42.0}],
        "risks": [{"code": "FALSE_BREAK", "summary": "突破仍需确认"}],
        "phase": "accumulation_d",
        "support": 38.0,
        "resistance": 43.0,
        "spring": False,
    }


def test_valid_json_is_converted_to_typed_engine_result() -> None:
    llm = FakeLLM(json.dumps(_valid_output(), ensure_ascii=False))
    engine = StructuredWyckoffEngine(llm, model="configured-model")

    result = engine.analyze(_snapshot(), CONTEXT)

    assert result.engine_score == 72
    assert result.evidence[0].code == "PHASE_D"
    assert result.risks[0].code == "FALSE_BREAK"
    assert dict(result.metadata)["phase"] == '"accumulation_d"'
    request = llm.requests[0]
    assert request.model == "fake-model"
    assert request.deadline == CONTEXT.deadline
    assert json.loads(request.response_schema)["additionalProperties"] is False


@pytest.mark.parametrize(
    "content",
    [
        "",
        "```json\n{}\n```",
        "not-json",
        json.dumps({**_valid_output(), "engine_score": 101}),
        json.dumps({key: value for key, value in _valid_output().items() if key != "narrative"}),
        json.dumps({**_valid_output(), "unexpected": "field"}),
    ],
)
def test_invalid_output_is_failure_not_neutral_score(content: str) -> None:
    engine = StructuredWyckoffEngine(FakeLLM(content), model="fake")

    with pytest.raises(StructuredOutputError) as error:
        engine.analyze(_snapshot(), CONTEXT)

    assert error.value.error_code == "INVALID_STRUCTURED_OUTPUT"
