"""Strict structured-output LLM engines for production analysis."""

from __future__ import annotations

import json
from abc import abstractmethod
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..enums import EngineMode
from ..infra.errors import DataUnavailableError, StructuredOutputError
from ..ports import LLMPort
from ..schema import (
    DataSnapshot,
    EngineCapabilities,
    EngineContext,
    EngineResult,
    Evidence,
    LLMRequest,
    Risk,
)
from .kernel import SnapshotAnalysisEngine
from .rating import score_to_rating


class _StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvidenceOutput(_StrictOutput):
    code: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=300)
    value: float | str | None = None


class RiskOutput(_StrictOutput):
    code: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=300)


class StructuredEngineOutput(_StrictOutput):
    engine_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    narrative: str = Field(min_length=1, max_length=1000)
    evidence: tuple[EvidenceOutput, ...] = Field(min_length=1, max_length=12)
    risks: tuple[RiskOutput, ...] = Field(default=(), max_length=12)


class WyckoffOutput(StructuredEngineOutput):
    phase: Literal[
        "accumulation_a",
        "accumulation_b",
        "accumulation_c",
        "accumulation_d",
        "accumulation_e",
        "distribution_a",
        "distribution_b",
        "distribution_c",
        "distribution_d",
        "distribution_e",
    ]
    support: float
    resistance: float
    spring: bool


class CANSLIMOutput(StructuredEngineOutput):
    c: float = Field(ge=0, le=15)
    a: float = Field(ge=0, le=15)
    n: float = Field(ge=0, le=15)
    s: float = Field(ge=0, le=15)
    leadership: float = Field(alias="l", ge=0, le=15)
    i: float = Field(ge=0, le=15)
    m: float = Field(ge=0, le=15)

    @model_validator(mode="after")
    def score_matches_dimensions(self) -> CANSLIMOutput:
        total = min(
            100.0,
            self.c + self.a + self.n + self.s + self.leadership + self.i + self.m,
        )
        if abs(total - self.engine_score) > 1:
            raise ValueError("engine_score must equal the capped CANSLIM dimension sum")
        return self


class BuffettOutput(StructuredEngineOutput):
    moat: float = Field(ge=0, le=20)
    financial_health: float = Field(ge=0, le=20)
    management: float = Field(ge=0, le=20)
    valuation: float = Field(ge=0, le=20)
    growth: float = Field(ge=0, le=20)

    @model_validator(mode="after")
    def score_matches_dimensions(self) -> BuffettOutput:
        total = self.moat + self.financial_health + self.management + self.valuation + self.growth
        if abs(total - self.engine_score) > 1:
            raise ValueError("engine_score must equal the Buffett dimension sum")
        return self


class StructuredLLMEngine(SnapshotAnalysisEngine):
    """Base for JSON-Schema constrained LLM explanations without code execution."""

    mode = EngineMode.LLM_STRUCTURED
    output_model: ClassVar[type[StructuredEngineOutput]]
    prompt_version = "v080-1"
    system_prompt: ClassVar[str]
    min_history_bars = 0
    needs_financials = False

    def __init__(self, llm: LLMPort, *, model: str) -> None:
        self._llm = llm
        self._model = model

    def capabilities(self) -> EngineCapabilities:
        required = ["quote"]
        if self.min_history_bars:
            required.append("historical")
        if self.needs_financials:
            required.append("financials")
        return EngineCapabilities(
            required_data=tuple(required),
            min_history_bars=self.min_history_bars,
            requires_llm=True,
            requires_sandbox=False,
            deterministic=False,
            timeout_seconds=20,
        )

    def analyze(self, snapshot: DataSnapshot, context: EngineContext) -> EngineResult:
        self._validate_snapshot(snapshot)
        request = LLMRequest(
            messages=(
                ("system", self.system_prompt),
                ("user", self._build_summary(snapshot)),
            ),
            response_schema=json.dumps(
                self.output_model.model_json_schema(),
                ensure_ascii=False,
                sort_keys=True,
            ),
            model=context.model or self._model,
            deadline=context.deadline,
        )
        response = self._llm.complete(request)
        if not response.content.strip():
            raise StructuredOutputError(self.name, snapshot.symbol, "empty LLM response")
        try:
            output = self.output_model.model_validate_json(response.content)
        except ValidationError as exc:
            raise StructuredOutputError(
                self.name,
                snapshot.symbol,
                f"schema validation failed: {exc.errors(include_url=False)}",
            ) from exc

        base_fields = {"engine_score", "confidence", "narrative", "evidence", "risks"}
        extra = output.model_dump(mode="json", exclude=base_fields)
        metadata = tuple(
            (key, json.dumps(value, ensure_ascii=False, sort_keys=True))
            for key, value in sorted(extra.items())
        )
        return EngineResult(
            engine_name=self.name,
            engine_version=self.version,
            symbol=snapshot.symbol,
            engine_score=output.engine_score,
            rating=score_to_rating(output.engine_score),
            confidence=output.confidence,
            narrative=output.narrative,
            evidence=tuple(
                Evidence(item.code, item.summary, item.value) for item in output.evidence
            ),
            risks=tuple(Risk(item.code, item.summary) for item in output.risks),
            metadata=metadata,
        )

    def _validate_snapshot(self, snapshot: DataSnapshot) -> None:
        if snapshot.quote is None or not snapshot.quote.succeeded:
            raise DataUnavailableError(f"quote is unavailable for {snapshot.symbol}")
        if self.min_history_bars:
            historical = snapshot.historical
            if historical is None or not historical.succeeded or historical.data is None:
                raise DataUnavailableError(f"history is unavailable for {snapshot.symbol}")
            if len(historical.data.bars) < self.min_history_bars:
                raise DataUnavailableError(
                    f"need >={self.min_history_bars} bars for {snapshot.symbol}"
                )
        if self.needs_financials:
            financials = snapshot.financials
            if financials is None or not financials.succeeded:
                raise DataUnavailableError(f"financials are unavailable for {snapshot.symbol}")

    @abstractmethod
    def _build_summary(self, snapshot: DataSnapshot) -> str:
        """Build a bounded prompt from precomputed snapshot facts."""

    @staticmethod
    def _market_summary(snapshot: DataSnapshot) -> str:
        quote = snapshot.quote.data
        assert quote is not None
        parts = [
            f"symbol={snapshot.symbol}",
            f"price={quote.price}",
            f"change_pct={quote.change_pct}",
            f"pe={quote.pe}",
            f"pb={quote.pb}",
        ]
        historical = snapshot.historical
        if historical and historical.succeeded and historical.data:
            bars = historical.data.bars
            closes = [bar.close for bar in bars]
            parts.extend(
                (
                    f"history_bars={len(bars)}",
                    f"close_min={min(closes)}",
                    f"close_max={max(closes)}",
                    f"recent_closes={closes[-20:]}",
                )
            )
        return "\n".join(parts)


class StructuredWyckoffEngine(StructuredLLMEngine):
    name = "wyckoff"
    version = "3.0.0"
    output_model = WyckoffOutput
    min_history_bars = 60
    system_prompt = (
        "Use Wyckoff price-volume structure. Return only JSON conforming to the supplied schema. "
        "Every claim must reference supplied facts; never invent missing data."
    )

    def _build_summary(self, snapshot: DataSnapshot) -> str:
        return self._market_summary(snapshot)


class StructuredCANSLIMEngine(StructuredLLMEngine):
    name = "can_slim"
    version = "3.0.0"
    output_model = CANSLIMOutput
    needs_financials = True
    system_prompt = (
        "Apply CANSLIM to the supplied market and financial facts. Return only strict schema JSON. "
        "Do not infer unavailable company events or institutional data."
    )

    def _build_summary(self, snapshot: DataSnapshot) -> str:
        financials = snapshot.financials.data
        assert financials is not None
        return (
            self._market_summary(snapshot)
            + "\n"
            + "\n".join(
                (
                    f"revenue_yoy={financials.revenue_yoy}",
                    f"profit_yoy={financials.profit_yoy}",
                    f"roe={financials.roe}",
                    f"debt_ratio={financials.debt_ratio}",
                )
            )
        )


class StructuredBuffettEngine(StructuredLLMEngine):
    name = "buffett"
    version = "3.0.0"
    output_model = BuffettOutput
    needs_financials = True
    system_prompt = (
        "Assess business quality, financial health, management evidence, valuation and growth. "
        "Return only strict schema JSON and explicitly treat absent evidence as a risk."
    )

    def _build_summary(self, snapshot: DataSnapshot) -> str:
        financials = snapshot.financials.data
        assert financials is not None
        return (
            self._market_summary(snapshot)
            + "\n"
            + "\n".join(
                (
                    f"roe={financials.roe}",
                    f"debt_ratio={financials.debt_ratio}",
                    f"revenue_yoy={financials.revenue_yoy}",
                    f"profit_yoy={financials.profit_yoy}",
                    f"gross_margin={financials.gross_margin}",
                    f"fcf={financials.fcf}",
                )
            )
        )
