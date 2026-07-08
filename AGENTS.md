# AGENTS.md — 谛听 开发手册

> **给 AI 开发者的施工规范。开始任何工作前，先读完这个文件。**

---

## 0. 项目速览

| 项目 | 谛听 (Diting) |
|------|-------------|
| 定位 | A股多模型AI投资分析工具 · 开源 Python 库 |
| 许可 | MIT |
| Python | 3.12+ |
| 包管理 | uv + pyproject.toml |
| 工作目录 | `~/workspace/diting` |
| 设计文档 | `docs/01-design/` |

### 关键外部依赖

| 包 | 用途 | 安装方式 |
|---|------|---------|
| `litellm` | 统一 100+ LLM provider 接口 | pip |
| `mcpaisuite-sandboxmcp` | Python 沙箱（seccomp+namespace） | pip |
| `click` | CLI 框架 | pip |
| `structlog` | 结构化日志 | pip |
| `vmdpy` | VMD 分解 | pip |
| `PyWavelets` | 小波去噪 | pip |
| `PyEMD` | CEEMDAN | pip |
| `openpyxl` | Excel 读取（mx-data 返回 xlsx） | pip |

---

## 1. 设计铁律（不可违反）

### 1.1 依赖方向

```
config ──→ 所有层
Layer 0 (infra) ──→ 不依赖任何业务层
Layer 1 (data)  ──→ L0
Layer 2 (signals)──→ L1 + L0
Layer 3 (engines)──→ L2 + L1
Layer 4 (pipeline)──→ L3 + L2 + L1
Layer 5 (cli/report/notify)──→ L4
```

**铁律：下层永远不 import 上层。** 违反 = 架构腐化。

### 1.2 数据协议

所有跨模块数据必须用 `@dataclass`，定义在 `src/diting/schema.py`。禁止裸传 dict/DataFrame。

```python
# ✅ 正确
result: AnalysisResult = engine.analyze(ctx)

# ❌ 错误
result = engine.analyze(ctx)  # 返回 dict，字段靠猜
```

### 1.3 引擎开发

- 所有分析引擎继承 `AnalysisEngine` ABC
- 用 `@register_engine("name")` 注册
- 新引擎 = 新建文件 + 继承 ABC + 加装饰器。**绝不改已有代码。**
- AI 驱动的引擎：LiteLLM 生成计算代码 → sandboxmcp 执行 → 返回结果

### 1.4 错误处理

```python
# ✅ 正确
logger.error("analysis.failed", engine="wyckoff", reason="ai_timeout")

# ❌ 错误
print("分析失败了")  # 绝对禁止 print
```

- 用 `structlog`，不用 `print`
- 一个引擎失败不阻塞其他引擎
- 数据源不可用时自动降级（mx-data → akshare → SQLite）

---

## 2. 目录结构

```
src/diting/
├── __init__.py
├── main.py              ← CLI 入口（click）
├── config.py            ← .env + watchlist.csv 解析
├── schema.py            ← 所有 @dataclass 协议
├── enums.py             ← Rating, DataSource, DataType, Signal
├── data/                ← Layer 1：数据访问
│   ├── repository.py    ← MarketDataRepository（降级链）
│   ├── cache.py         ← TTL 缓存
│   └── providers/
│       ├── base.py      ← DataProvider ABC
│       ├── mx_data.py   ← 东方财富
│       └── akshare.py   ← akshare 兜底
├── signals/             ← Layer 2：信号处理
│   ├── technical.py     ← RSI/MACD/KDJ/布林/VWAP
│   ├── vmd.py           ← VMD 分解
│   ├── wavelet.py       ← 小波去噪
│   └── ceemdan.py       ← CEEMDAN
├── engines/             ← Layer 3：分析引擎
│   ├── base.py          ← AnalysisEngine ABC
│   ├── registry.py      ← @register_engine 插件机制
│   ├── wyckoff.py       ← 威克夫（AI + 沙箱）
│   ├── buffett.py       ← 巴菲特/芒格（AI + 沙箱）
│   ├── can_slim.py      ← CANSLIM（AI + 沙箱）
│   ├── volume_profile.py← Volume Profile（纯计算）
│   └── vmd_rsi.py       ← VMD+RSI 择时（纯计算）
├── pipeline/            ← Layer 4：编排
│   ├── runner.py        ← AnalysisPipeline
│   ├── consensus.py     ← 多引擎评分融合
│   └── pipeline.yaml    ← 管道配置
├── report/              ← Layer 5：报告
│   ├── builder.py       ← ReportBuilder
│   ├── echarts.py       ← ECharts 图表
│   └── templates/       ← HTML 模板
├── notify/              ← Layer 5：推送
│   ├── base.py          ← Notifier ABC
│   ├── feishu.py
│   ├── email.py
│   └── local.py
├── sandbox/             ← Python 沙箱
│   └── executor.py      ← sandboxmcp 封装
├── ai/                  ← AI Provider
│   └── client.py        ← LiteLLM 封装
├── infra/               ← Layer 0：基础设施
│   ├── logging_config.py← structlog 配置
│   ├── errors.py        ← 异常层次结构
│   └── decorators.py    ← @cached @retry @log_latency
config/
├── .env.example         ← 环境变量模板（无真实值）
├── watchlist.example.csv
└── pipeline.yaml
tests/
├── unit/
├── integration/
└── fixtures/
output/                  ← 报告输出（.gitignore）
```

---

## 3. 开发流程

### 3.0 分工铁律

| 角色 | 干什么 | 不干什么 |
|------|--------|---------|
| **小爪** | 设计文档、架构、Issue 拆分、写 prompt | 不写代码、不改 .py、不跑测试 |
| **CodeWhale** | 所有代码实现 + 写测试 + 验证 + 通知海桐 | 不改设计、不改 AGENTS.md（本文件除外） |

**所有编码工作必须通过 CodeWhale 执行**。小爪只做规划和审核，不直接写代码。

### 3.1 拿到 Issue 后的标准步骤

1. **读相关设计文档**：`docs/01-design/` 下找到对应设计
2. **读 agent.md**：目标目录下如果有 `agent.md`，先读
3. **派给 CodeWhale**：把 Issue 写成清晰的任务描述，包含目标文件、产出要求、验收标准
4. **CodeWhale 写代码**：遵循本文档的所有规则
5. **CodeWhale 写测试 + 验证**：`pytest` + `ruff check` 通过
6. **小爪审核**：review 代码变更，确认符合设计
7. **通知海桐**：执行 `scripts/notify-diting.sh "Mx 标题" "完成/失败摘要"`，把进展发到海桐飞书私聊

### 3.2 测试要求

| 层 | 覆盖目标 |
|----|:------:|
| infra (errors/decorators) | >90% |
| data (providers) | >80% |
| signals (指标计算) | >80% |
| engines (AI 驱动) | >60%（mock AI + 真实沙箱） |
| pipeline/cli | >50%（smoke test） |

---

## 4. AI 引擎开发规范

### 4.1 引擎结构模板

```python
@register_engine("engine_name")
class MyEngine(AnalysisEngine):
    name = "engine_name"
    version = "1.0.0"

    def required_data(self) -> list[DataType]:
        return [DataType.REALTIME, DataType.HISTORICAL]

    def analyze(self, ctx: AnalysisContext) -> AnalysisResult:
        # Step 1: AI 规划计算代码
        code = self._plan_computation(ctx)

        # Step 2: 沙箱执行
        result = sandbox.run(code)

        # Step 3: 如果失败，traceback 喂给 AI 重试 1 次
        if result.errors:
            code = self._fix_code(code, result.errors)
            result = sandbox.run(code)

        # Step 4: 构建结果
        return AnalysisResult(
            engine_name=self.name,
            symbol=ctx.symbol,
            score=result["score"],
            rating=self._to_rating(result["score"]),
            signals=result.get("signals", []),
            narrative=result.get("narrative", ""),
            charts=[],
            risks=result.get("risks", []),
            confidence=result.get("confidence", 0.5),
            computation_log=result.audit_id,
            metadata={},
        )
```

### 4.2 LiteLLM 调用规范

```python
from diting.ai.client import llm

# 所有 AI 调用走这个统一接口
response = llm.completion(
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ],
    max_tokens=4000,
)
```

### 4.3 沙箱调用规范

```python
from diting.sandbox.executor import sandbox

result = sandbox.run(code)
# → SandboxResult(output=..., errors=[...], execution_time_ms=123, audit_id="abc")
```

沙箱配置（在 `config/.env` 中）：
- `SANDBOX_BACKEND=process`（零额外依赖）
- `SANDBOX_MEMORY_MB=512`
- `SANDBOX_TIMEOUT=60`
- 允许的 import：numpy, pandas, scipy, vmdpy, PyWavelets, PyEMD, openpyxl

---

## 5. 关键避坑指南

### 5.1 数据源

- **个股和 ETF 分开查**：mx-data 混合查询会截断 ETF 数据
- **每批不超过 4 只**：批量查询可能静默丢失部分标的
- **ETF 用代码不用简称**：`159770` 而非 "机器人业"，简称可能匹配到行业板块
- **ETF 复权单位净值 ≠ 涨跌幅**：用收盘价直接算

### 5.2 VMD

- **参数顺序**：`VMD(signal, alpha, tau, K, DC, init, tol)` — tau 和 K 互换会报错
- **输出比输入短 1**：`len(u[0]) = len(input) - 1`
- **内存泄漏**：每次调用后 `del u, _, om` + `gc.collect()`
- **窗口约束**：数据必须 ≥ `K * 10` 天

### 5.3 mx-data 查询措辞

- `"股票名 历史收盘价 2026-01-01 至 2026-06-30"` → 日线（正确）
- `"股票名 近一年收盘价"` → 只返回 2 行（错误！）
- 返回的收盘价格式 `66.24元`，需要清理 "元" 字后转 float

### 5.4 cron job 模型必须 Pin

如果用 cron job，必须显式传 model 参数，否则全局模型切换后静默失败。

### 5.5 文件创建

- 所有新文件包含模块 docstring
- 用 `uv run` 运行命令，不用裸 `python`
- 配置模板不含真实值：`.env.example` 而非 `.env`

---

## 6. 开始工作前必读

**优先级顺序：**

1. 本文档（AGENTS.md）
2. `docs/01-design/architecture.md` — 完整架构
3. `docs/01-design/data-models.md` — 所有 @dataclass 定义
4. `docs/01-design/api-contracts.md` — CLI + Python API + 配置
5. `docs/01-design/development-workflow.md` — 开发流程
6. `docs/01-design/issue-plan.md` — Issue 拆分（当前任务清单）

**调研参考（需要背景知识时读）：**
7. `docs/02-research/wyckoff-method.md`
8. `docs/02-research/buffett-munger-a-share.md`
9. `docs/02-research/signal-processing-methods.md`

---

*文档维护：小爪 | 谛听项目组 | 2026-07-08*

## 7. 通知海桐

每次任务完成后，向海桐报告进展。用小爪 bot 身份发到飞书私聊。

### 7.1 命令

```bash
./scripts/notify-diting.sh "Mx 标题" "完成/失败摘要（可多行）"
```

用小爪 bot 的飞书 API 凭据直接发消息到海桐私聊。不需要 lark-cli，纯 Python + urllib。

### 7.2 流程

```
CodeWhale 执行完任务
  → 跑 scripts/notify-diting.sh
    → Python 调用飞书 API（小爪 bot app_id + app_secret）
      → 海桐飞书私聊收到（发件人：小爪）
```
