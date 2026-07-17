# 谛听 全系统数据流规范 v1.0

> 覆盖所有数据通路、层间协议、错误处理、新鲜度传递。  
> 每条通路都标注了当前状态（✅正常 / ⚠️有缺陷 / ❌损坏）。

---

## 0. 系统总览

```
┌──────────┐   ┌──────────────┐   ┌────────────┐   ┌───────────┐   ┌────────┐
│ External │ → │ Data Layer   │ → │ Web Layer  │ → │ FastAPI   │ → │ 浏览器 │
│ APIs     │   │ Provider→Repo│   │ Service    │   │ Router    │   │  SPA   │
│ mx-data  │   │ →Cache Layer │   │ →Response  │   │ → JSON    │   │ modules│
│ EastMoney│   │              │   │            │   │ envelope  │   │ →DOM   │
└──────────┘   └──────────────┘   └────────────┘   └───────────┘   └────────┘
```

**核心原则：** 数据从源头到浏览器，每一层必须显式传递 `freshness`（数据时间、来源、是否过期）。当前系统各层断裂——无一处完整传递。

---

## 一、数据流 #1: 大盘仪表盘

### 1.1 通路

```
mx-data / EastMoney API
    │
    ├→ repo.get_realtime(["000001.SH","399001","399006"])
    │
    ├→ repo.get_historical("000001.SH", 250d)
    │       └→ VMDDecomposer.decompose() → vmd_cycle
    │
    ├→ dashboard_service.get_market_sentiment()
    │       └→ repo.get_realtime(["000001.SH"])
    │
    ├→ scan_service.get_opportunities() → buy/watch/hold/avoid count
    │
    └→ DashboardService.get_dashboard_data()
            │
            ├→ L1: cm.mem_get_adaptive("dashboard", trading_ttl=60) ⚠️
            ├→ L2: cm.db_get("dashboard_cache", "1") ⚠️
            ├→ L3: 构建 result dict + mem_set + db_set
            │
            └→ FastAPI _api_response()
                └→ {server_time, cache_state, data}
```

### 1.2 当前缺陷 ⚠️

| 位置 | 缺陷 | 影响 |
|------|------|------|
| L1 `mem_get_adaptive` | 缓存命中 → 强行标记 `_cache_state="stale"` | 用户总看到"可能滞后" |
| L3 `result` dict | 无 `freshness` 字段 | 前端不知道数据实际时间 |
| `api_dashboard` | 从 data 中 pop `_cache_state`，但 service 返回的 dict 里没这个字段 → 永远 fallback 到 `"fresh"` | 缓存永远显示 fresh |
| 股票指数 API | 无 timestamp 传递 | 不知数据何时产生 |

### 1.3 修复规范

```python
# dashboard service 返回
@dataclass
class DashboardResult:
    data: dict
    freshness: FreshnessInfo         # 新增：数据新鲜度
    cache_level: Literal["L1","L2","L3"]  # 新增：命中层级

# route 层
def api_dashboard():
    result = dashboard_service.get_dashboard_data()
    return _api_response(
        data=result.data,
        freshness=result.freshness,
        cache_state="stale" if result.cache_level != "L3" else "fresh"
    )
```

---

## 二、数据流 #2: 个股分析

### 2.1 通路

```
mx-data / EastMoney
    │
    ├→ StockService.get_realtime(code)
    │   ├→ L1: mem_get_adaptive → RealtimeQuote
    │   ├→ L2: db_get("watchlist_cache") → RealtimeQuote
    │   └→ L3: repo.get_realtime([code])
    │
    ├→ StockService.get_historical(code, 250d)
    │
    ├→ TechnicalCalculator.calculate(historical) → signals ⚠️
    │
    ├→ VMDDecomposer.decompose(close_vals)
    │
    ├→ EastMoneyProvider.fetch_fund_flow(code)
    │
    ├→ AnalysisPipeline(engine_names).run([ctx])
    │   ├→ wyckoff, buffett, can_slim (AI + sandbox)
    │   ├→ volume_profile, vmd_rsi (纯计算)
    │   └→ verdict (结论翻译)
    │
    ├→ ConsensusEngine.fuse() → ConsensusScore
    │
    └→ StockService.analyze_stock(code)
        ├→ L1: mem_get_adaptive(f"analysis:{code}")
        ├→ L2: db_get("stock_analysis_cache", code) ❌
        ├→ L3: 全流程分析 + db_set
        └→ StockAnalysisResponse dataclass
```

### 2.2 当前缺陷

| 位置 | 缺陷 | 影响 |
|------|------|------|
| L2 `db_get("stock_analysis_cache")` | SQLite 行解包错误: `not enough values to unpack (expected 2, got 1)` ❌ | 搜索 000001 后页面空白 |
| `analyze_stock` 返回值 | `StockAnalysisResponse` 无 `freshness` 字段 | 前端无数据时间 |
| `clean_numpy` → `_json.dumps` 序列化 | `default=str` 把 dataclass 转成字符串 | chart_data 可能丢失 |
| AI 引擎 | 无 API key 时静默跳过 | 评分永远基于 quick_score |

### 2.3 修复规范

```python
# DB 解包修复
def db_get(self, table: str, key: str) -> dict | None:
    cur = conn.execute(f"SELECT * FROM {table} WHERE {pk_col}=?", (key,))
    row = cur.fetchone()
    if row is None: return None
    cols = [d[0] for d in cur.description]
    # 防御：列数 ≠ 行字段数 → 用命名索引而非 zip
    result = {}
    for i, col in enumerate(cols):
        if i < len(row):
            result[col] = row[i]
    return result
```

---

## 三、数据流 #3: 设置管理

### 3.1 通路

```
浏览器 settings.html
    │
    ├→ GET /api/settings
    │   └→ DashboardService.get_settings()
    │       ├→ Config().load()
    │       ├→ _load_saved_settings() → SQLite settings 表
    │       └→ 合并为 {provider_toggles, ai_model, engine_toggles}
    │
    ├→ POST /api/settings
    │   └→ DashboardService.save_settings(data)
    │       └→ db.set_setting(key, str(val))
    │
    └→ 前端渲染 settings.js → 显示所有 toggle
```

### 3.2 当前状态

| 项 | 状态 |
|----|:---:|
| 后端 API 返回 | ✅ |
| 前端渲染 | ❌ 页面空白 |

---

## 四、数据流 #4: 自选股

### 4.1 通路

```
浏览器
    │
    ├→ GET /api/watchlist
    │   └→ WatchlistService.get_watchlist()
    │       ├→ Config().load_watchlist() → [{code, name}]
    │       ├→ 逐只 StockService.get_realtime(code) → 实时行情
    │       └→ [{code, name, price, change_pct, ...}]
    │
    ├→ POST /api/watchlist {code, name, market}
    │   └→ WatchlistService.add_watchlist()
    │       └→ Config().add_to_watchlist()
    │
    └→ DELETE /api/watchlist/{code}
        └→ WatchlistService.remove_watchlist()
```

### 4.2 当前状态

| 项 | 状态 |
|----|:---:|
| 后端 API | ✅ |
| 前端渲染 | ⚠️ 仅标题，无数据卡片 |

---

## 五、数据流 #5: 选股机会

### 5.1 通路

```
ScanService.get_opportunities()
    │
    ├→ L1: mem_get_adaptive("opportunities")
    ├→ L2: db_get("market_scan_cache", batch_id)
    ├→ L3: 全市场扫描
    │   ├→ 遍历所有 A 股
    │   ├→ 每只 quick_score → 分类 buy/watch/hold/avoid
    │   └→ Top N 按 score 排序
    │
    └→ {items, strong_buy, watch, avoid}
```

### 5.2 当前状态

| 项 | 状态 |
|----|:---:|
| 后端 API | ✅ |
| 前端渲染 | ❌ 页面空白 |

---

## 六、数据流 #6: 新鲜度传递（全栈设计）

### 6.1 当前系统：新鲜度在每一层断裂

```
Provider.fetch()         → 返回数据，无 timestamp ❌
Repository.get_realtime() → 返回 RealtimeQuote，有 price 无 fetch_time ❌
Cache.mem_set()          → 存数据，TTL 基于写入时间，非数据时间 ❌
Service.get_xxx()        → 返回 data dict，无 freshness ❌
Router._api_response()   → server_time = datetime.now(UTC) ← 这是服务器时间！
Frontend                 → "数据更新于 {server_time}" ← 误标为数据时间！
```

### 6.2 目标架构：端到端传递 data_time

```
Provider.fetch()
  → (data, data_time=response["timestamp"])    # 数据产生时间

Repository.get_realtime()
  → RealtimeQuote(..., fetch_time=data_time)   # 新增字段

Cache.set(..., fresh_until=data_time + TTL)    # 过期时间基于数据时间

Service.get_xxx()
  → {data, freshness: {data_time, source, stale_since}}

Router._api_response()
  → {"server_time": now(), "data": ..., "freshness": {data_time, source}}

Frontend
  → "数据更新于 {data_time}"  // 真实的数据时间
  → 根据 stale_since 显示"已过期"警告
```

### 6.3 FreshnessInfo 协议

```python
@dataclass
class FreshnessInfo:
    """数据新鲜度，每层显式传递"""
    data_time: datetime | None     # 数据实际产生时间（provider 返回）
    source: str                    # 数据来源 (mx-data/eastmoney/akshare/cache)
    cached_at: datetime            # 缓存写入时间
    fresh_until: datetime | None   # 数据有效期
    is_stale: bool                 # 是否已过期

    @property
    def age_seconds(self) -> int:
        if self.data_time:
            return int((datetime.now(UTC) - self.data_time).total_seconds())
        return -1
```

### 6.4 前端显示规范

```javascript
// 数据新鲜度显示规则
function _dataTimeBar(freshness) {
    const age = freshness.age_seconds;
    if (age < 60)           return `🟢 实时 · ${freshness.source}`;
    if (age < 300)          return `🟡 ${Math.floor(age/60)}分钟前 · ${freshness.source}`;
    if (freshness.is_stale) return `🔴 数据过期 · ${freshness.source}`;
    return `⚪ 已缓存 · ${freshness.source}`;
}
```

---

## 七、前端渲染数据流

### 7.1 模块加载链 ✅

```
index.html
  → core.js        (状态+工具, 无依赖)
  → cache.js       (浏览器缓存)
  → api.js         (API 封装, API_BASE=/api/diting)
  → charts.js      (ECharts 包装)
  → ui.js          (UI 组件)
  → pages/*.js     (仪表盘/个股/选股/自选/设置)
  → router.js      (hash 路由)
  → app.js         (入口, DOMContentLoaded → renderPage)
```

### 7.2 页面渲染流程

```
app.js: renderPage()
  → router.js: resolveRoute(location.hash)
  → dispatch to page render function
  → page.js: _loadWithCache(key, skeleton, apiFn, renderFn)
      ├→ cacheManager.getStale(key) → 立即渲染旧数据
      ├→ apiFn() → fetch /api/diting/xxx
      ├→ renderFn(data) → 更新 DOM
      └→ cacheManager.set(key, data) → 保存缓存
```

### 7.3 当前页面状态

| 页面 | 渲染函数 | 状态 | 问题 |
|------|---------|:---:|------|
| dashboard.js | renderDashboard | ✅ | 数据正常但 stale |
| stock.js | renderStockSearch / renderStock | ❌ | 语法错误 + 骨架代码 |
| opportunities.js | renderOpportunities | ❌ | render 返回空 |
| watchlist.js | renderWatchlist | ⚠️ | 缺数据卡片 |
| settings.js | renderSettings | ❌ | render 返回空 |

### 7.4 修复策略：组件化重构

```
frontend/js/
├── components/        ← 新增：可复用组件
│   ├── search-bar.js  ← 搜索框+下拉建议
│   ├── data-card.js   ← 通用数据卡片
│   ├── score-bar.js   ← 评分进度条
│   ├── indicator.js   ← 技术指标展示
│   ├── skeleton.js    ← 骨架屏
│   └── freshness.js   ← 新鲜度指示器
├── pages/
│   ├── dashboard.js   ← 重构：使用组件组装
│   ├── stock.js       ← 重写：从 git 恢复+修复语法
│   ├── opportunities.js← 重构
│   ├── watchlist.js   ← 重构
│   └── settings.js    ← 重构
```

---

## 八、错误处理规范

### 8.1 当前问题

- 数据源失败 → `try/except: pass` 静默吞掉
- API 返回空 → 前端白屏
- 无降级方案从缓存回退

### 8.2 各层错误处理规范

```
Provider      → 失败抛 DataUnavailableError（含 provider_name, reason）
Repository    → 降级链：provider1 → provider2 → cache → DataUnavailableError
Cache         → db_get 失败返回 None（不抛异常）
Service       → 捕获异常，返回含 error 字段的 result
Router        → 捕获 DataUnavailableError → 返回 503 + {error, fallback_available}
Frontend      → _loadWithCache 自动降级：API 失败 → 缓存数据 → 错误提示
```

---

## 九、缓存分层与 TTL 规范

| 数据 | L1 (内存) | L2 (SQLite) | L3 (API) |
|------|-----------|-------------|----------|
| 实时行情 | 30s (盘中) / 5min (盘后) | 当日有效 | force_refresh=true |
| 个股分析 | 60s (盘中) | result_json, expires_at | 可 force_refresh |
| 仪表盘 | 60s (盘中) | data_json | 可 force_refresh |
| 市场情绪 | 300s | 无 | 可 force_refresh |
| 选股机会 | 600s | Top 20, batch_id | 后台扫描 |
| 历史日线 | 600s | 无 | 按需获取 |

**fresh_until 计算规则：** `data_time + TTL`，非 `cache_set_time + TTL`。

---

## 十、优先级执行计划

| Phase | 内容 | 工作量 |
|-------|------|:---:|
| **P0** | 修复 stock_analysis_cache DB 解包错误 | 小 |
| **P0** | 实现 FreshnessInfo 全栈协议 + API 响应对齐 | 中 |
| **P1** | 修复 DashboardService cache_state 传递 | 小 |
| **P1** | 重构前端页面为组件化（stock/opportunities/settings优先） | 大 |
| **P2** | 重写 stock.js 完整版（从旧单体恢复） | 中 |
| **P3** | Playwright E2E 测试集成 | 中 |
