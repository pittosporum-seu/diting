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
# 标准/深度分析；第一条也可简写为 `diting 002475`
diting analyze 002475 --profile standard
diting analyze 002475 --profile deep

# 行情读取与同口径比较（只经过缓存数据网关，不触发分析）
diting quote 002475 --freshness cache_preferred
diting compare 002475,600519 --json

# 只运行人工激活的机会策略
diting scan --limit 20

# 本机 owner 状态与服务
diting watchlist
diting watchlist --add 002475 --name 立讯精密 --market SZ --tag 核心
diting strategy --json
diting serve --host 127.0.0.1 --port 8100
```

`l0`、`l1`、`l2`、`run` 和旧配置向导在 v0.8 已删除并返回
`CLI_COMMAND_REMOVED`。所有命令可通过全局 `--config FILE` 指定严格 YAML 配置。

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
