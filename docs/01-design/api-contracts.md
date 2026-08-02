# 谛听 · API 契约

> 版本：v0.8.0 | 日期：2026-08-02
> REST API 契约见 `docs/api/diting-openapi.yaml`

---

## Python API

```python
from diting import AnalysisProfile, Diting, FetchMode

with Diting.from_config("config/diting.yaml") as client:
    # 所有数据读取都经过 L1/L2 缓存中间层。
    quote = client.get_quote("002475", freshness=FetchMode.CACHE_PREFERRED)
    # -> DataResult[RealtimeQuote]

    run = client.analyze("002475", profile=AnalysisProfile.STANDARD)
    # -> AnalysisRun；失败引擎不会伪造成 50 分

    opportunities = client.scan(limit=20)
    # -> ScanResult；无 active 策略时 error_code == "NO_ACTIVE_STRATEGY"
```

配置优先级为调用参数 `overrides` > 环境变量 > YAML > 默认值。`Diting` 也支持显式
`close()`；关闭后继续调用会抛出 `RuntimeError`。v0.8 不提供 L0/L1/L2 Python 别名。

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
