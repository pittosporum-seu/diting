"""谛听 · AiOutputParser 单元测试

覆盖：正常JSON / markdown代码块 / numpy类型清洗 / 残缺JSON / ast回退 / parse_static
"""

from __future__ import annotations

import pytest

from diting.ai.output_parser import AiOutputParser
from diting.ai.output_schema import AiEngineOutput
from diting.enums import Rating


class TestAiOutputParser:
    """AiOutputParser.parse() 测试"""

    # ── 正常 JSON ──

    def test_parse_valid_json(self):
        raw = '{"score": 75, "narrative": "测试分析", "confidence": 0.8}'
        result = AiOutputParser.parse(raw)
        assert isinstance(result, AiEngineOutput)
        assert result.score == 75.0
        assert result.narrative == "测试分析"
        assert result.confidence == 0.8
        assert result.rating == Rating.BUY  # 75 >= 65

    def test_parse_minimal_json(self):
        raw = '{"score": 50}'
        result = AiOutputParser.parse(raw)
        assert result.score == 50.0
        assert result.narrative == ""
        assert result.rating == Rating.ACCUMULATE  # 50 >= 50

    # ── 含 risks 和 signals ──

    def test_parse_with_risks_and_signals(self):
        raw = (
            '{"score": 60, "narrative": "中等", "risks": ["风险1", "风险2"], '
            '"signals": ["sig1", "sig2"]}'
        )
        result = AiOutputParser.parse(raw)
        assert result.risks == ["风险1", "风险2"]
        assert result.signals == ["sig1", "sig2"]

    def test_parse_with_structured_reasons(self):
        raw = (
            '{"score": 70, "bull_reasons": ["盈利增长", "估值合理"], '
            '"bear_reasons": ["行业波动"]}'
        )
        result = AiOutputParser.parse(raw)
        assert result.bull_reasons == ["盈利增长", "估值合理"]
        assert result.bear_reasons == ["行业波动"]
        assert "bull_reasons" not in result.metadata
        assert "bear_reasons" not in result.metadata

    def test_missing_structured_reasons_default_to_empty_lists(self):
        result = AiOutputParser.parse('{"score": 50}')
        assert result.bull_reasons == []
        assert result.bear_reasons == []

    def test_parse_signals_as_string(self):
        raw = '{"score": 60, "signals": "spring_detected"}'
        result = AiOutputParser.parse(raw)
        assert result.signals == ["spring_detected"]

    # ── warnings → risks 兼容（buffett） ──

    def test_parse_warnings_maps_to_risks(self):
        raw = '{"score": 65, "warnings": ["高负债率", "ROE下降"]}'
        result = AiOutputParser.parse(raw)
        assert result.risks == ["高负债率", "ROE下降"]

    def test_parse_risks_has_priority_over_warnings(self):
        raw = '{"score": 65, "risks": ["风险A"], "warnings": ["警告B"]}'
        result = AiOutputParser.parse(raw)
        assert result.risks == ["风险A"]

    # ── 引擎特有字段 → metadata ──

    def test_parse_extra_fields_go_to_metadata(self):
        raw = '{"score": 70, "narrative": "分析", "moat_score": 15, "phase": "Phase C"}'
        result = AiOutputParser.parse(raw)
        assert result.metadata == {"moat_score": 15, "phase": "Phase C"}

    # ── markdown 代码块 ──

    def test_parse_markdown_code_block(self):
        raw = '```json\n{"score": 80, "narrative": "强势"}\n```'
        result = AiOutputParser.parse(raw)
        assert result.score == 80.0
        assert result.narrative == "强势"

    def test_parse_embedded_in_text(self):
        raw = 'Analysis result: {"score": 55, "narrative": "一般"} End.'
        result = AiOutputParser.parse(raw)
        assert result.score == 55.0
        assert result.narrative == "一般"

    # ── numpy 类型清洗 ──

    def test_parse_numpy_float64(self):
        raw = '{"score": np.float64(75.5), "narrative": "test"}'
        result = AiOutputParser.parse(raw)
        assert result.score == 75.5

    def test_parse_numpy_int64(self):
        raw = '{"score": np.int64(80), "narrative": "test"}'
        result = AiOutputParser.parse(raw)
        assert result.score == 80.0

    def test_parse_numpy_bool_false(self):
        raw = '{"score": 50, "spring_detected": np.False_}'
        result = AiOutputParser.parse(raw)
        assert result.metadata.get("spring_detected") is False

    def test_parse_numpy_bool_true(self):
        raw = '{"score": 50, "sos_detected": np.True_}'
        result = AiOutputParser.parse(raw)
        assert result.metadata.get("sos_detected") is True

    def test_parse_numpy_bool_with_parens(self):
        raw = '{"score": 50, "flag": np.bool_(True)}'
        result = AiOutputParser.parse(raw)
        assert result.metadata.get("flag") is True

    def test_parse_mixed_numpy_types(self):
        raw = (
            '{"score": np.float64(68.5), "count": np.int64(3), '
            '"spring_detected": np.False_, "volume_confirmation": np.bool_(True)}'
        )
        result = AiOutputParser.parse(raw)
        assert result.score == 68.5
        assert result.metadata.get("count") == 3
        assert result.metadata.get("spring_detected") is False
        assert result.metadata.get("volume_confirmation") is True

    # ── Python dict 字面量（ast.literal_eval 回退） ──

    def test_parse_python_dict_single_quotes(self):
        raw = "{'score': 70, 'narrative': '中文分析', 'phase': 'Phase D'}"
        result = AiOutputParser.parse(raw)
        assert result.score == 70.0
        assert result.narrative == "中文分析"
        assert result.metadata.get("phase") == "Phase D"

    def test_parse_python_dict_with_numpy(self):
        raw = "{'score': np.float64(82.3), 'narrative': '测试', 'detected': np.False_}"
        result = AiOutputParser.parse(raw)
        assert result.score == 82.3
        assert result.metadata.get("detected") is False

    # ── 边界/异常 ──

    def test_parse_empty_string(self):
        result = AiOutputParser.parse("")
        assert result.score == 50.0
        assert result.narrative == ""
        assert result.rating == Rating.ACCUMULATE

    def test_parse_none_output(self):
        result = AiOutputParser.parse("")
        assert result.score == 50.0

    def test_parse_no_braces(self):
        result = AiOutputParser.parse("no json here")
        assert result.score == 50.0

    def test_parse_malformed_json(self):
        result = AiOutputParser.parse('{"score": 65, "narrative": ')
        assert result.score == 50.0  # 回退到默认

    def test_parse_score_clamped(self):
        raw = '{"score": 150, "narrative": "test"}'
        result = AiOutputParser.parse(raw)
        assert result.score == 100.0  # clamp to max

        raw = '{"score": -10, "narrative": "test"}'
        result = AiOutputParser.parse(raw)
        assert result.score == 0.0  # clamp to min

    # ── 评分 → 评级 ──

    @pytest.mark.parametrize("score,expected_rating", [
        (95, Rating.STRONG_BUY),
        (80, Rating.STRONG_BUY),
        (79, Rating.BUY),
        (65, Rating.BUY),
        (64, Rating.ACCUMULATE),
        (50, Rating.ACCUMULATE),
        (49, Rating.HOLD),
        (35, Rating.HOLD),
        (34, Rating.REDUCE),
        (20, Rating.REDUCE),
        (19, Rating.SELL),
        (0, Rating.SELL),
    ])
    def test_score_to_rating(self, score, expected_rating):
        raw = f'{{"score": {score}, "narrative": "test"}}'
        result = AiOutputParser.parse(raw)
        assert result.rating == expected_rating


class TestAiOutputParserStatic:
    """AiOutputParser.parse_static() 测试"""

    def test_parse_static_same_as_parse(self):
        raw = '{"score": 72, "narrative": "静态测试", "risks": ["风险X"]}'
        result = AiOutputParser.parse_static(raw)
        assert isinstance(result, AiEngineOutput)
        assert result.score == 72.0
        assert result.narrative == "静态测试"
        assert result.risks == ["风险X"]

    def test_parse_static_empty(self):
        result = AiOutputParser.parse_static("")
        assert result.score == 50.0


class TestAiOutputParserInternals:
    """AiOutputParser 内部方法测试"""

    def test_clean_numpy_json_target(self):
        text = "np.float64(44.57) np.int64(10) np.False_ np.True_ np.bool_(False)"
        result = AiOutputParser._clean_numpy(text, target="json")
        assert "44.57" in result
        assert "10" in result
        assert "false" in result
        assert "true" in result
        assert "False" in result  # np.bool_(False) → False
        assert "np." not in result  # all cleaned

    def test_clean_numpy_python_target(self):
        text = "np.float64(44.57) np.False_ np.True_"
        result = AiOutputParser._clean_numpy(text, target="python")
        assert "44.57" in result
        assert "False" in result
        assert "True" in result
        assert "np." not in result

    def test_clean_numpy_float128(self):
        text = "np.float128(99.999)"
        result = AiOutputParser._clean_numpy(text, target="json")
        assert "99.999" in result
        assert "np." not in result


class TestAiEngineOutput:
    """AiEngineOutput dataclass 测试"""

    def test_default_values(self):
        output = AiEngineOutput(score=50.0)
        assert output.rating == Rating.HOLD
        assert output.narrative == ""
        assert output.signals == []
        assert output.risks == []
        assert output.bull_reasons == []
        assert output.bear_reasons == []
        assert output.confidence == 0.5
        assert output.metadata == {}

    def test_all_fields_set(self):
        output = AiEngineOutput(
            score=85.0,
            rating=Rating.STRONG_BUY,
            narrative="强势买入",
            signals=["signal1"],
            risks=["risk1"],
            bull_reasons=["bull1"],
            bear_reasons=["bear1"],
            confidence=0.9,
            metadata={"moat_score": 18},
        )
        assert output.score == 85.0
        assert output.rating == Rating.STRONG_BUY
        assert output.narrative == "强势买入"
        assert output.signals == ["signal1"]
        assert output.risks == ["risk1"]
        assert output.bull_reasons == ["bull1"]
        assert output.bear_reasons == ["bear1"]
        assert output.confidence == 0.9
        assert output.metadata == {"moat_score": 18}
