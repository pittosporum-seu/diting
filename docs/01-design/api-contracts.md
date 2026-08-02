# 谛听 · API 契约

> 版本：v1.0 | 日期：2026-07-04
> REST API 契约见 `docs/api/diting-openapi.yaml`

---

## Python API

```python
from diting import Diting, AnalysisConfig

# === 快速模式 ===
diting = Diting(level="L0")

# 单只行情快照
quote = diting.quick_scan("002475")
# → RealtimeQuote(symbol="002475", name="立讯精密", price=70.4, change_pct=2.1, ...)

# 批量
quotes = diting.quick_scan(["002475", "603659", "159851"])
# → dict[str, RealtimeQuote]

# === 标准分析 (L1) ===
diting_l1 = Diting(level="L1", config=AnalysisConfig(
    engines=["wyckoff", "vmd_rsi"],
    notifiers=["feishu"],
))

result = diting_l1.analyze("002475")
# → AnalysisResult(engine_name="wyckoff", score=65, rating=BUY, ...)

# 批量
results = diting_l1.analyze(["002475", "603659"])
# → PipelineResult(symbols=..., results=..., consensus=...)

# === 深度分析 (L2) ===
diting_l2 = Diting(level="L2", config=AnalysisConfig(
    engines="all",  # 所有已注册引擎
    notifiers=["feishu", "email", "local"],
    report_format=["html", "pdf"],
))

results = diting_l2.deep_analyze(["002475"])
# → PipelineResult(..., reports={"html": "/path/to/report.html", "pdf": "..."})
```

## CLI

```bash
# L0: 快速行情
diting l0 --symbols 002475,603659
diting l0 --watchlist config/watchlist.csv

# L1: 标准分析
diting l1 --symbols 002475 --engines wyckoff,vmd_rsi
diting l1 --watchlist config/watchlist.csv --notify feishu

# L2: 深度分析
diting l2 --symbols 002475 --engines all
diting l2 --watchlist config/watchlist.csv --notify feishu,email
diting l2 --watchlist config/watchlist.csv --output ./reports/

# 自动选择层级（按 .env DITING_LEVEL）
diting run --symbols 002475
```

## 配置 (.env)

```bash
# 层级
DITING_LEVEL=L1

# 数据源
MX_APIKEY=***
AKSHARE_ENABLED=true

# AI（LiteLLM — 统一 100+ provider）
AI_MODEL=deepseek/deepseek-v4-pro    # 格式: provider/model
# 切换示例: openai/gpt-4o, anthropic/claude-sonnet-4
AI_API_KEY=***

# 沙箱（sandboxmcp — seccomp + namespace 隔离）
SANDBOX_BACKEND=process              # process | docker
SANDBOX_MEMORY_MB=512
SANDBOX_TIMEOUT=60
SANDBOX_ALLOWED_IMPORTS=numpy,pandas,scipy,vmdpy,PyWavelets,PyEMD,openpyxl

# 推送
NOTIFY_DEFAULT=feishu
FEISHU_APP_ID=
FEISHU_APP_SECRET=
EMAIL_SMTP_HOST=
EMAIL_FROM=
EMAIL_TO=

# 缓存
CACHE_REALTIME_TTL=3600
CACHE_HISTORICAL_TTL=86400
```

## 管道配置 (pipeline.yaml)

```yaml
# 引擎权重
engines:
  wyckoff:
    enabled: true
    weight: 0.30
    timeout: 60
  buffett:
    enabled: false  # L1 不跑
    weight: 0.25
  vmd_rsi:
    enabled: true
    weight: 0.35
  technical:
    enabled: true
    weight: 0.35

# 评分融合
consensus:
  method: weighted_average
  conflict_threshold: 2.0  # 两引擎评分差 >20 标记冲突
  min_engines: 1           # 至少几个引擎成功才出结果

# 报告
report:
  template: l1
  charts: true
  include_raw_data: false

# 推送
notify:
  channels: [feishu]
  summary_max_chars: 200
  attach_report: false
```

## 引擎扩展接口

```python
# 注册新引擎
from diting.engines import register_engine, AnalysisEngine, AnalysisContext, AnalysisResult

@register_engine("my_custom")
class MyCustomEngine(AnalysisEngine):
    name = "my_custom"
    version = "1.0.0"

    def required_data(self) -> list[DataType]:
        return [DataType.REALTIME, DataType.HISTORICAL]

    def analyze(self, ctx: AnalysisContext) -> AnalysisResult:
        # AI 规划 + Python 沙箱执行
        code = self._plan_computation(ctx)
        result = self._sandbox.execute(code)
        return AnalysisResult(
            engine_name=self.name,
            symbol=ctx.symbol,
            score=result["score"],
            rating=Rating.BUY,
            ...
        )
```

---

*文档维护：小爪 | 谛听项目组 | 2026-07-04*
