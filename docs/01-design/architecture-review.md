# 谛听 · 全项目架构审查报告

> 审查日期：2026-07-13 | 审查范围：src/diting/ + frontend/ + tests/ + config/ + docs/
> 审查方法：逐文件静态分析 + 交叉比对 + 设计文档对照

---

## 目录

1. [问题总览](#1-问题总览)
2. [逐类问题详解](#2-逐类问题详解)
   - [2.1 重复代码](#21-重复代码)
   - [2.2 不统一的设计](#22-不统一的设计)
   - [2.3 分层问题](#23-分层问题)
   - [2.4 前后端不一致](#24-前后端不一致)
   - [2.5 降级/错误处理缺失](#25-降级错误处理缺失)
   - [2.6 配置与代码不匹配](#26-配置与代码不匹配)
   - [2.7 测试覆盖不足](#27-测试覆盖不足)
3. [严重度评级汇总](#3-严重度评级汇总)
4. [统一方案设计](#4-统一方案设计)
5. [实施建议](#5-实施建议)
6. [不改的](#6-不改的)

---

## 1. 问题总览

| # | 问题 | 类别 | 严重度 | 所在文件 |
|---|------|------|:------:|---------|
| 1 | `_parse_output` 3 份几乎相同的实现 | 重复代码 | **P0** | engines/buffett.py, wyckoff.py, can_slim.py |
| 2 | `_to_rating` 6 个引擎 + Consensus + services 各有实现 | 重复代码 | **P0** | 6 个引擎文件 + consensus.py + services.py |
| 3 | 两份 TTLCache（web/cache.py vs cache/cache_manager.py） | 重复代码 | **P1** | web/cache.py, cache/cache_manager.py |
| 4 | `_extract_chart_arrays` 的列名探测重复多次 | 重复代码 | P2 | web/services.py, get_dashboard_data 等处 |
| 5 | AI 引擎各自定义输出 schema（不统一） | 不统一设计 | **P0** | buffett.py, wyckoff.py, can_slim.py |
| 6 | `_to_rating` 阈值不统一（6 档 vs 4 档 vs 配置驱动） | 不统一设计 | **P0** | 8 处独立实现 |
| 7 | 前端缓存：cacheManager + _swr 两套机制 | 不统一设计 | **P1** | app.js, api.js |
| 8 | services.py 1435 行（缓存+数据+编排+路由桥接） | 分层问题 | **P1** | web/services.py |
| 9 | app.js 1586 行（路由+渲染+缓存+UI） | 分层问题 | **P1** | frontend/js/app.js |
| 10 | analyze_stock 返回裸 dict 违反 schema 铁律 | 分层问题 | **P1** | web/services.py |
| 11 | engine_scores 字段名后端用 "name"，前端图表面用 "name"（待确认为 "engine"） | 前后端不一致 | P2 | services.py, app.js |
| 12 | 无统一 API 错误响应格式 | 错误处理缺失 | **P0** | web/routes.py |
| 13 | bull_reasons / bear_reasons 用叙事文本关键词匹配 | 脆弱设计 | **P1** | web/services.py:596-608 |
| 14 | AI 引擎无降级：无 key 时静默跳过但 pipeline 仍有 None | 错误处理缺失 | **P1** | web/services.py:517-527 |
| 15 | eltdx 仍存在于配置和 UI，但 _build_repo 已不初始化 | 配置-代码不匹配 | **P1** | config/diting.yaml, services.py:1262 |
| 16 | AGENTS.md 引用的设计文档不存在 | 文档不匹配 | P2 | AGENTS.md 第 292-295 行 |
| 17 | 引擎单元测试覆盖为 0（wyckoff/buffett/can_slim/volume_profile/vmd_rsi） | 测试不足 | **P1** | tests/ |
| 18 | 无统一的 AiOutput 数据协议 | 不统一设计 | **P1** | schema.py |
| 19 | 列名探测 "close"/"收盘价" 逻辑散落 4 处 | 重复代码 | P2 | services.py, 各引擎 |
| 20 | 前端模块缓存版本不统一（app.js v0.6.6, CSS v0.7.0） | 前后端不一致 | P2 | frontend/index.html |

---

## 2. 逐类问题详解

### 2.1 重复代码

#### 问题 1：`_parse_output` 三份实现

**位置：**
- `src/diting/engines/buffett.py:100-137`（38 行，含 numpy 清洗）
- `src/diting/engines/wyckoff.py:185-222`（38 行，含 numpy 清洗，与 buffett **逐行相同**）
- `src/diting/engines/can_slim.py:84-109`（26 行，简化版，**无 numpy 清洗**）

**根因：** 3 个 AI 引擎各自在 class 内部实现 `_parse_output`，没有抽取到基类或公共工具模块。

**影响：**
- 改一处需要改三处（如新增 numpy 类型清洗规则）
- can_slim 缺少 numpy 清洗，沙箱输出含 `np.float64()` 时会解析失败
- 代码膨胀：共 102 行重复代码

**统一方案：**
抽取 `AiOutputParser.parse(output: str) -> dict` 到 `src/diting/ai/output_parser.py`，基类 `AnalysisEngine` 提供默认实现，引擎可覆写。

---

#### 问题 2：`_to_rating` 评分映射重复 8 处

**位置：**

| 文件 | 行号 | 阈值 |
|------|:---:|------|
| engines/buffett.py | 140-151 | 80/65/50/35/20 → STRONG_BUY/BUY/ACC/HOLD/REDUCE/SELL |
| engines/wyckoff.py | 225-237 | 同上（6 档） |
| engines/can_slim.py | 112-123 | 同上（6 档） |
| engines/vmd_rsi.py | 81-92 | 同上（6 档） |
| engines/verdict.py | 128-135 | **75/55/35** → BUY/ACC/HOLD/REDUCE（**只有 4 档，无 STRONG_BUY/SELL**） |
| engines/volume_profile.py | — | 无独立 `_to_rating`，硬编码判断（3 个分支） |
| pipeline/consensus.py | 91-107 | 从 `config/diting.yaml` 读阈值（配置驱动，唯一一处不硬编码） |
| web/services.py | 1181-1188 | 75/55/35 → buy/accumulate/hold/reduce（**4 档，返回字符串而非 Rating enum**） |

**根因：** `AnalysisEngine` ABC 没有提供默认实现，每个引擎自己写了一遍。

**影响：**
- 阈值不统一：verdict 和 quick_score 用 75/55/35，AI 引擎用 80/65/50/35/20
- verdict 和 volume_profile **永远不会产生 STRONG_BUY 或 SELL 评级**，导致共识偏差
- services.py 和 consensus.py 各自映射 Rating→中文标签，也做了重复

**统一方案：**
1. 在 `AnalysisEngine` 基类中增加 `_score_to_rating(score, thresholds=None)` 方法
2. 所有引擎统一调用基类方法
3. 阈值从 `config/diting.yaml` 的 `engines.scoring.threshold` 读取

---

#### 问题 3：两份 TTLCache 实现

**位置：**
- `src/diting/web/cache.py:12-60` — `TTLCache` 类（用于 7 个模块级缓存实例）
- `src/diting/cache/cache_manager.py:102-150` — `_TTLCache` 类（CacheManager 内部使用）

**根因：** `web/cache.py` 在 v0.4 创建，`cache/cache_manager.py` 在 v0.5 创建，两者独立演化。

**影响：**
- 功能重叠但行为不完全一致
- `web/cache.py` 有 `AdaptiveTTLCache` 子类支持 MarketState-aware TTL
- `cache/cache_manager.py` 的 `_TTLCache` 没有这个能力
- 维护两套代码，改 bug 可能只改一处

**统一方案：**
弃用 `web/cache.py` 的 `TTLCache`，统一使用 `CacheManager` 的内存层。将 `AdaptiveTTLCache` 的能力整合到 `CacheManager.mem_get()` 中。

---

#### 问题 4：列名探测重复

**位置（至少 4 处）：**
- `web/services.py:177-190` — `_extract_chart_arrays` 中的 `col_map` 探测
- `web/services.py:548-550` — VMD 计算中的 close 列探测
- `web/services.py:788-797` — dashboard VMD 中的 close 列探测
- `engines/volume_profile.py:32` — `"close" if "close" in df.columns else "收盘价"`

**根因：** 数据源（不同 provider）返回不同列名，但没有统一的列名规范化层。

**统一方案：**
在 `MarketDataRepository` 层增加列名规范化方法 `_normalize_columns(df) -> DataFrame`，将中文列名统一为英文标准名。

---

### 2.2 不统一的设计

#### 问题 5：AI 引擎各自定义输出 schema

**位置：** 3 个 AI 引擎的 system prompt 中

| 引擎 | 输出字段 |
|------|---------|
| buffett | score, moat_score, financial_score, management_score, valuation_score, growth_score, warnings, narrative |
| wyckoff | phase, score, spring_detected, sos_detected, support_level, resistance_level, volume_confirmation, narrative |
| can_slim | score, c_score, a_score, n_score, s_score, l_score, i_score, m_score, narrative |

**共同字段：** 只有 `score` 和 `narrative`。其他完全各异。

**解析方式：**
- buffett: `result.get("output", "")` → `_parse_output` → `parsed.get("score")/get("narrative")/get("warnings")`
- wyckoff: `result.get("output", "")` → `_parse_output` → `parsed.get("phase")/get("spring_detected")/...
- can_slim: `result.get("output", "")` → `_parse_output` → `parsed.get("score")/get("narrative")`

**根因：** 没有统一的 `AiOutput` 数据协议。

**统一方案：**
在 `schema.py` 中新增 `AiEngineOutput` dataclass：

```python
@dataclass(frozen=True)
class AiEngineOutput:
    """AI 引擎沙箱输出标准协议"""
    score: float
    narrative: str
    sub_scores: dict[str, float] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
```

引擎各自的 system prompt 中要求 AI 输出符合此格式，解析统一走 `AiOutputParser`。

---

#### 问题 6：`_to_rating` 阈值不统一

（已在问题 2 中详述）

---

#### 问题 7：前端两套缓存机制

**位置：**
- `app.js:10-95` — `cacheManager`（TTL 5min, STALE_MAX_AGE 30min, VERSION=2）
- `api.js:51-111` — `_swr()` 函数（独立 TTL, PREFIX='diting_swr_', 无版本管理）

**根因：** v0.6.0 加了 `cacheManager`，v0.7.0 在 api.js 又加了 `_swr`，两者并存。

**影响：**
- 两套独立的 localStorage 键前缀（`diting_cache_` vs `diting_swr_`）
- `_swr` 无版本管理，升级后可能读到旧格式数据
- `_swr` 无 `getStale` 能力（`cacheManager` 有）
- 部分页面用 `_loadWithCache`（调用 `cacheManager`），部分用 `_swr`，不一致

**统一方案：**
弃用 `_swr`，统一使用 `cacheManager`（它功能更全，有版本管理、stale 支持和 prune）。

---

### 2.3 分层问题

#### 问题 8：services.py 过重（1435 行）

**位置：** `src/diting/web/services.py`

**当前职责混合：**
| 职责 | 行号范围 | 大约行数 |
|------|:---:|:---:|
| 缓存逻辑（L1/L2 读写） | 多处 | ~200 |
| 数据获取（实时/历史） | 273-400 | ~130 |
| 数据分析（analyze_stock） | 402-660 | ~260 |
| 仪表盘编排 | 686-857 | ~170 |
| 选股扫描（watchlist+market） | 974-1148 | ~175 |
| 自选股 CRUD | 74-88 | ~15 |
| 设置管理 | 1246-1340 | ~95 |
| 搜索 | 1342-1400 | ~60 |
| 缓存管理 | 1406-1435 | ~30 |
| 工具函数 | 多处 | ~300 |

**问题：** 一个类承担了 10 种职责，任何修改都可能影响其他功能。

**v0.7.0 重设计方案已提出拆分**（见 `docs/01-design/v0.7.0-redesign.md` §3.3）：
- StockService
- DashboardService
- WatchlistService
- ScanService
- SettingsService

**当前状态：已设计、未实施。**

---

#### 问题 9：app.js 单体（1586 行）

**位置：** `frontend/js/app.js`

**当前职责混合：**
- 路由解析（`ROUTE_MAP`, `resolveRoute`, `renderPage`）
- 缓存管理（`cacheManager`）
- UI 组件库（`ui.statGrid`, `ui.statCard`, `ui.table` 等）
- 5 个页面的渲染函数
- 搜索建议组件
- 自选股添加逻辑
- 设置页面 toggle/模型切换逻辑
- 缓存统计加载

**统一方案：**
建议拆分为 `router.js`, `cache.js`, `ui.js`, `pages/dashboard.js`, `pages/stock.js`, `pages/opportunities.js`, `pages/watchlist.js`, `pages/settings.js`。

---

#### 问题 10：analyze_stock 返回裸 dict 违反 AGENTS.md 铁律

**位置：** `web/services.py:402-660`

**AGENTS.md §1.2 明确规定：**
> 所有跨模块数据必须用 `@dataclass`，定义在 `src/diting/schema.py`。禁止裸传 dict/DataFrame。

**现实：** `analyze_stock()` 返回 `dict`，包含 `code`, `name`, `price`, `score`, `engine_scores`, `bull_reasons`, `chart_data` 等 20+ 个字段。

**影响：**
- 前端无法获知返回结构，只能 `data.xxx` 靠猜
- 后端改字段名前端不感知
- 无类型提示，IDE 无法辅助

**统一方案：**
增加 `StockAnalysisResponse` dataclass，`analyze_stock` 返回此类型，routes.py 负责序列化。

---

### 2.4 前后端不一致

#### 问题 11：engine_scores 字段名

**后端** (`services.py:583-589`)：
```python
engine_scores.append({
    "name": r.engine_name,     # ← 用 "name"
    "score": r.score,
    "rating": r.rating.value,
    ...
})
```

**前端** (`app.js:847-850`)：
```javascript
charts.renderEngineBars('engine-bars', engineScores.map(es => ({
    name: es.name,    // ← 也用 "name"
    score: es.score,
})));
```

**现状：一致（都用 "name"）。但文档中提到的 "有的用 name 有的用 engine" 已不存在。** 降级为 P2 提醒：应统一为 "engine_name" 以与 `AnalysisResult.engine_name` 保持一致。

---

#### 问题 12：前端模块版本号不一致

**位置：** `frontend/index.html:7-12`

```html
<link rel="stylesheet" href="css/styles.css?v=0.6.6">
<link rel="stylesheet" href="css/freshness.css?v=0.7.0">  <!-- v0.7.0 -->
<script type="module" src="js/api.js?v=0.6.6">
<script type="module" src="js/charts.js?v=0.6.6">
<script type="module" src="js/app.js?v=0.6.6">
```

`freshness.css` 版本号为 v0.7.0，其余为 v0.6.6。不影响功能但说明增量修改的疏忽。

---

### 2.5 降级/错误处理缺失

#### 问题 13：无统一 API 错误响应格式

**位置：** `web/routes.py`

**当前：**
- 成功响应：`_api_response(data, cache_state)` → `{server_time, cache_state, data}`
- 错误响应：`raise HTTPException(status_code=404)` → FastAPI 默认格式 `{detail: "..."}`

**问题：** 错误响应没有 `server_time`、`cache_state`，前端解析逻辑不统一。

**v0.7.0 重设计已规划**（见 `docs/01-design/v0.7.0-redesign.md` §5.1）但未实施：

```json
{"server_time": "...", "error": {"code": "NOT_FOUND", "message": "..."}}
```

---

#### 问题 14：bull_reasons / bear_reasons 关键字匹配脆弱

**位置：** `web/services.py:591-608`

```python
if any(kw in line for kw in ["买入", "看多", "低估", "超卖", "支撑", "利好"]):
    bull_reasons.append(line[:60])
elif any(kw in line for kw in ["卖出", "看空", "高估", "超买", "阻力", "风险", "利空"]):
    bear_reasons.append(line[:60])
```

**问题：**
- 依赖 AI 输出叙事文本中包含这些关键词
- 关键词覆盖不全（如缺少 "增持"、"减持"、"泡沫"、"破位"）
- "支撑" 和 "阻力" 可能同时出现在一句话中
- 截断到 60 字符可能丢失关键信息

**统一方案：**
引擎的 `AnalysisResult` 应直接提供 `bull_reasons` / `bear_reasons` 列表（如 verdict.py 已在 metadata 中提供），services.py 从各引擎结果中收集，不再从 narrative 文本中提取。

---

#### 问题 15：AI 引擎降级不完整

**位置：** `web/services.py:515-541`

**当前逻辑：**
1. 无 API key → 跳过 AI 引擎（wyckoff, buffett, can_slim）
2. 非交易时段 → 跳过 AI 引擎

**问题：**
- AI 引擎被静默跳过，用户看到的是纯计算引擎的评分（volume_profile + vmd_rsi + verdict）
- 评分从原本 6 引擎变成 3 引擎，但前端仍显示"由 N 个引擎综合评估"，用户不知道缺少了维度
- `pipeline.run()` 被 `try/except` 包裹，异常被吞掉 → consensus 回退为 50 分 default

**统一方案：**
- 在 `engine_scores` 中增加 `skipped` 列表，标记哪些引擎被跳过及原因
- 前端显示 "X 个引擎参与评估（Y 个暂不可用）"

---

### 2.6 配置与代码不匹配

#### 问题 16：eltdx 存在于配置但代码已不初始化

**位置：**

| 位置 | 具体内容 |
|------|---------|
| `config/diting.yaml:7-9` | `providers: [{name: eltdx, priority: 10, auto_detect: true}]` |
| `web/services.py:1262` | `_ALL_PROVIDER_KEYS = ["provider_eltdx", "provider_ashare", ...]` |
| `web/services.py:1280` | label map 含 `"eltdx": "eltdx (通达信直连)"` |
| `web/services.py:1286` | `"requires_api_key": pk in ("provider_eltdx", "provider_mxdata")` |
| 前端设置页面 (app.js:1434) | 描述文字 `降级链顺序：eltdx → ashare → mx-data → akshare` |
| `web/services.py:112-156` | `_build_repo()` **没有实例化 eltdx** |

**影响：**
- `.env` 中设置 `provider_eltdx=1` 不会产生任何效果（不报错但也不起作用）
- 前端设置 toggle 显示 "eltdx (通达信直连)" 但开关无效
- 优先级最高的数据源配置实际上被忽略

**统一方案：**
1. 如果 eltdx 要恢复：在 `_build_repo` 中加上初始化逻辑
2. 如果 eltdx 要移除：清理 `config/diting.yaml`、`_ALL_PROVIDER_KEYS`、前端 UI、label map

---

#### 问题 17：AGENTS.md 引用不存在的文档

**位置：** `AGENTS.md:292-295`

```markdown
2. `docs/01-design/architecture.md` — 完整架构
3. `docs/01-design/data-models.md` — 所有 @dataclass 定义
4. `docs/01-design/api-contracts.md` — CLI + Python API + 配置
5. `docs/01-design/development-workflow.md` — 开发流程
```

**实际存在的文件：**
- ~~architecture.md~~ → `architecture-overview.md`
- ~~data-models.md~~ → 不存在，schema 定义在 `src/diting/schema.py`
- ~~api-contracts.md~~ → 存在但内容偏向配置说明
- ~~development-workflow.md~~ → 存在
- ~~issue-plan.md~~ → 存在

---

### 2.7 测试覆盖不足

#### 问题 18：引擎层单元测试为零

**测试现状：**

| 模块 | 测试文件 | 状态 |
|------|---------|:---:|
| schema.py | tests/unit/test_schema.py | ✅ 有 |
| verdict engine | tests/unit/test_verdict.py | ✅ 有（307 行，覆盖全面） |
| wyckoff engine | — | ❌ 无 |
| buffett engine | — | ❌ 无 |
| can_slim engine | — | ❌ 无 |
| volume_profile engine | — | ❌ 无 |
| vmd_rsi engine | — | ❌ 无 |
| pipeline runner | tests/unit/test_ai_timeout.py | ✅ 有（但只测超时，不测正常流程） |
| consensus | — | ❌ 无独立测试 |
| AI client | — | ❌ 无 |
| sandbox executor | — | ❌ 无 |
| data providers | tests/unit/test_data_providers.py | ✅ 有 |
| cache manager | tests/unit/test_cache_defense.py | ✅ 有 |
| config | tests/unit/test_config.py | ✅ 有 |

**AGENTS.md 覆盖目标：**
| 层 | 目标 | 实际 |
|----|:---:|:---:|
| infra | >90% | ~60%（test_infra.py 存在但需确认覆盖度） |
| data | >80% | ~50%（providers 部分覆盖，repository 无测试） |
| signals | >80% | ~30%（test_technical.py + test_signals_advanced.py 存在） |
| engines | >60% | **~10%**（仅 verdict 有） |
| pipeline/cli | >50% | ~20%（仅 timeout 场景） |

---

#### 问题 19：缺少 schema 输出验证测试

**当前：** `test_schema.py` 只测 dataclass 创建，不测序列化/反序列化完整性。

**缺失：**
- `RealtimeQuote` → JSON 序列化往返测试
- `AnalysisResult` → 空 signals/risks 边界测试
- `PipelineResult` → 带错误结果的完整性测试

---

## 3. 严重度评级汇总

### P0（必须修 — 阻塞新功能或造成数据不一致）

| # | 问题 | 理由 |
|---|------|------|
| 1 | `_parse_output` 重复 ×3 | 改 bug 需要改 3 处，can_slim 缺失 numpy 清洗 |
| 2 | `_to_rating` 重复 ×8 | 阈值不统一，verdict/volume_profile 永不输出 STRONG_BUY/SELL |
| 5 | AI 输出 schema 不统一 | 每个引擎定义不同字段，后端解析逻辑无法统一 |
| 6 | 评分阈值不统一 | 影响共识融合的准确性 |
| 12 | 无统一错误响应格式 | 前端错误处理逻辑分裂 |

### P1（应该修 — 影响可维护性和扩展性）

| # | 问题 |
|---|------|
| 3 | 两份 TTLCache |
| 7 | 前端双缓存机制 |
| 8 | services.py 过重 |
| 9 | app.js 单体 |
| 10 | analyze_stock 返回裸 dict |
| 13 | bull/bear reasons 关键字匹配 |
| 14 | AI 引擎降级信息不透明 |
| 15 | eltdx 配置-代码不匹配 |
| 17 | 引擎无单元测试 |
| 18 | 缺少 AiOutput 数据协议 |

### P2（可以修 — 不影响功能但改善一致性）

| # | 问题 |
|---|------|
| 4 | 列名探测重复 |
| 11 | engine_scores 字段名建议统一 |
| 16 | 前端版本号不一致 |
| 19 | schema 输出验证测试 |
| 20 | AGENTS.md 文档链接过期 |

---

## 4. 统一方案设计

### 4.1 AI 引擎统一架构

```
当前（分散）:
  buffett.py: SYSTEM_PROMPT → _parse_output → AnalysisResult
  wyckoff.py: SYSTEM_PROMPT → _parse_output → AnalysisResult  ← 各自为政
  can_slim.py: SYSTEM_PROMPT → _parse_output → AnalysisResult

统一后:
  src/diting/ai/
  ├── client.py          ← LiteLLM（不变）
  ├── output_parser.py   ← AiOutputParser.parse()（统一解析）★ 新增
  ├── output_schema.py   ← AiEngineOutput dataclass（统一协议）★ 新增
  └── engine_adapter.py  ← AiEngineAdapter.run(system, user) → AiEngineOutput ★ 新增

  engines/
  ├── base.py: AnalysisEngine._run_ai(system_prompt, user_prompt) → AiEngineOutput
  ├── buffett.py: 调用 self._run_ai()，只定义 SYSTEM_PROMPT
  ├── wyckoff.py: 同上
  └── can_slim.py: 同上
```

### 4.2 评分评级统一

```python
# src/diting/engines/rating.py（新增）
from ..enums import Rating

# 默认阈值（config 可覆盖）
DEFAULT_THRESHOLDS = (80, 65, 50, 35, 20)

def score_to_rating(score: float, thresholds=None) -> Rating:
    """唯一权威的评分→评级映射"""
    t = thresholds or DEFAULT_THRESHOLDS
    if score >= t[0]: return Rating.STRONG_BUY
    if score >= t[1]: return Rating.BUY
    if score >= t[2]: return Rating.ACCUMULATE
    if score >= t[3]: return Rating.HOLD
    if score >= t[4]: return Rating.REDUCE
    return Rating.SELL
```

所有引擎和 Consensus 统一调用此函数。

### 4.3 缓存统一

```
当前:
  web/cache.py: 7 个 TTLCache/AdaptiveTTLCache 模块级实例
  cache/cache_manager.py: _TTLCache（私有）+ CacheManager
  api.js: _swr() 函数
  app.js: cacheManager 对象

统一后:
  后端: CacheManager（唯一缓存入口）
    ├── L1: MarketState-aware TTLCache（合并 AdaptiveTTLCache 能力）
    ├── L2: SQLite（不变）
    └── L1 缓存实例由 CacheManager 管理（不再模块级散落）

  前端: cacheManager（唯一缓存入口，废弃 _swr）
    ├── VERSION 管理
    ├── STALE_MAX_AGE
    └── prune() 自动清理
```

### 4.4 服务层拆分

按 `v0.7.0-redesign.md` §3.3 方案：

```
src/diting/web/
├── app.py              ← FastAPI 启动（不变）
├── routes.py           ← 路由 + _api_response 包装（不变）
├── services/           ← ★ 拆分（取代 services.py）
│   ├── __init__.py
│   ├── stock.py        ← StockService: analyze_stock, get_realtime, get_historical
│   ├── dashboard.py    ← DashboardService: get_dashboard_data
│   ├── watchlist.py    ← WatchlistService: CRUD + get_watchlist
│   ├── scan.py         ← ScanService: opportunities, market_scan
│   └── settings.py     ← SettingsService: get/save settings
├── cache.py            ← ★ 清理后只保留 AdaptiveTTLCache 迁移到 cache/
└── response.py         ← ★ 统一响应格式（_api_response 增强版）
```

### 4.5 统一 API 响应格式

```python
# 成功
{"server_time": "2026-07-13T14:35:22Z", "cache_state": "fresh|stale", "data": {...}}

# 错误
{"server_time": "2026-07-13T14:35:22Z", "error": {"code": "NOT_FOUND", "message": "未找到股票 999999"}}

# 实现：routes.py 中全局异常处理器 + _api_response 增强
```

### 4.6 数据协议补全

```python
# schema.py 新增

@dataclass(frozen=True)
class AiEngineOutput:
    """AI 引擎沙箱输出的统一协议"""
    score: float
    narrative: str
    sub_scores: dict[str, float] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    bull_reasons: list[str] = field(default_factory=list)
    bear_reasons: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

@dataclass
class StockAnalysisResponse:
    """analyze_stock 的返回协议"""
    code: str
    name: str
    price: float
    change_pct: float
    pe: float | None
    pb: float | None
    total_mv: float | None
    score: float
    rating: str
    rating_label: str
    rating_emoji: str
    confidence: float
    engine_scores: list[EngineScoreItem]
    engine_skipped: list[EngineSkipInfo]  # ★ 新增
    bull_reasons: list[str]
    bear_reasons: list[str]
    rsi_display: str
    macd_display: str
    chart_data: dict
    signals_summary: dict | None
    error: str | None
```

---

## 5. 实施建议

### 5.1 修复顺序（考虑依赖关系）

```
Round 1: 基础设施统一（无依赖，可并行）
├── 1.1 抽取 AiOutputParser + AiEngineOutput 协议
├── 1.2 统一 score_to_rating() 函数
├── 1.3 统一 API 响应格式（routes.py 增强）
└── 1.4 清理 eltdx 或恢复 eltdx

Round 2: 消除重复（依赖 Round 1）
├── 2.1 所有引擎改用基类 _run_ai() + AiOutputParser
├── 2.2 所有引擎改用统一 score_to_rating()
├── 2.3 前端统一用 cacheManager（废弃 _swr）
└── 2.4 融合两份 TTLCache

Round 3: 重构分层（依赖 Round 2）
├── 3.1 services.py 拆分为 5 个 service 模块
├── 3.2 analyze_stock 返回 StockAnalysisResponse dataclass
└── 3.3 app.js 拆分为多文件

Round 4: 补充测试和文档（依赖 Round 1-3）
├── 4.1 所有引擎单元测试
├── 4.2 schema 往返序列化测试
└── 4.3 更新 AGENTS.md 文档链接
```

### 5.2 各 Round 预估工作量

| Round | 工作量 | 风险 |
|:------|:------:|:-----|
| Round 1 | 2-3 天 | 低 — 纯新增/聚合，不改现有逻辑 |
| Round 2 | 3-4 天 | 中 — 改引擎和缓存，需全量回归测试 |
| Round 3 | 5-7 天 | 高 — services.py 和 app.js 是大文件，拆分需谨慎 |
| Round 4 | 2-3 天 | 低 — 补充测试不影响已有功能 |

**总计：约 12-17 天**

### 5.3 关键依赖关系图

```
AiOutputParser ──→ 引擎基类 _run_ai() ──→ 各引擎简化
score_to_rating() ──→ 所有引擎 + Consensus ──→ 阈值统一
统一响应格式 ──→ routes.py 改造 ──→ 前端错误处理统一
CacheManager 增强 ──→ web/cache.py 废弃 ──→ services.py 缓存逻辑简化
services.py 拆分 ──→ app.js 拆分（前端页面独立）
```

---

## 6. 不改的

以下内容经审查后确认保持现状：

| 项目 | 理由 |
|------|------|
| `routes.py` 的路由设计 | 职责清晰，12 个端点足够，`_api_response` 包装合理 |
| `api.js` 的网络请求封装 | 职责单一，`_request` 干净 |
| `pipeline/runner.py` 的并行执行模型 | ThreadPoolExecutor + as_completed 设计正确，超时机制合理 |
| `cache/market_state.py` 的交易日历 | 硬编码 2026 年节假日 OK，年底更新即可 |
| `sandbox/executor.py` 的沙箱设计 | sandboxmcp 封装清晰，`run_with_retry` 模式正确 |
| `ai/client.py` 的 LiteLLM 封装 | 接口简洁，日志完整 |
| `config.py` 的 .env 加载逻辑 | 分层合理（os.environ > .env 文件） |
| `infra/errors.py` 的异常层次 | 4 级异常结构清晰 |
| `infra/decorators.py` 的 @cached/@retry/@log_latency | 通用装饰器合理，引入后未被广泛使用是好事（预留能力） |
| `auth.yaml` 和 `diting-keepalive.service` | 运维文件，与代码架构无关 |
| `docs/02-research/` 目录 | 调研参考文档，不需要审查 |
| 前端 `charts.js` | 图表渲染逻辑独立，与架构问题无关 |
| Jinja2 模板 `search.html/result.html` | 遗留模板，现代码路径主要通过 SPA，保留无影响 |

---

*审查完成 · 文档输出：`docs/01-design/architecture-review.md`*
