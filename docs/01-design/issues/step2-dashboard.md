# Issue: Step 2 — Dashboard 接入 FreshnessInfo

type: feat
design_ref: docs/01-design/v0.1.0-backend-design.md (第3节 FreshnessInfo + 第4节测试规则)
depends_on: step1-infra ✅

## 目标

DashboardService 接入 Step 1 新增的 FreshnessInfo 协议，让仪表盘 API 返回真实数据新鲜度。

## 1. DashboardService.get_dashboard_data()

**文件：** `src/diting/web/services/dashboard.py`

**当前问题：**
- 第 67-72 行：L1 缓存命中 → 硬编码 `_cache_state = "stale"` → 永远显示"可能滞后"
- 第 79-91 行：L2 缓存命中 → 同样硬编码 stale
- 第 185-197 行：L3 构建 result 无 freshness 信息

**修复：** 每层缓存命中时记录数据来源和时间，最终在返回时构建 FreshnessInfo。

```python
def get_dashboard_data(self, force_refresh=False):
    freshness = None

    # L1: 内存
    if not force_refresh:
        cached = cm.mem_get_adaptive("dashboard", trading_ttl=60)
        if cached is not None:
            freshness = FreshnessInfo(
                data_time=cached.get("_cached_at"),
                source="memory_cache",
                is_fresh=False,
                age_seconds=...,
                ttl_seconds=60
            )
            cached.pop("_cached_at", None)
            return cached, freshness

    # L2: SQLite
    # ...

    # L3: API 请求
    result = {...}
    cm.mem_set("dashboard", {**result, "_cached_at": datetime.now(UTC)})
    freshness = FreshnessInfo(
        data_time=datetime.now(UTC),
        source="mx-data",
        is_fresh=True,
        age_seconds=0,
        ttl_seconds=60
    )
    return result, freshness
```

## 2. API 路由对齐

**文件：** `src/diting/web/routes.py` 第 114-118 行

当前：
```python
@router.get("/api/dashboard")
async def api_dashboard():
    data = dashboard_service.get_dashboard_data()
    cs = data.get("_cache_state", "fresh")
    return _api_response(data, cache_state=cs)
```

改为：
```python
@router.get("/api/dashboard")
async def api_dashboard():
    data, freshness = dashboard_service.get_dashboard_data()
    return _api_response(data, freshness=freshness)
```

## 3. get_market_sentiment 同样接入

`get_market_sentiment()` 返回的 dict 中加入时间戳，route 层提取为 FreshnessInfo。

## 验收标准

- [ ] pytest 全绿（新增测试覆盖 L1/L2/L3 三级 freshness）
- [ ] `curl /api/dashboard` 返回的 JSON 含 `freshness: {data_time, source, is_fresh, age_seconds, ttl_seconds}`
- [ ] `curl /api/market-sentiment` 同样含 freshness
- [ ] L1 命中: source=memory_cache, is_fresh=false
- [ ] L3 刷新: source=mx-data, is_fresh=true
- [ ] ruff check 零问题

## 约束

- 不修改 AGENTS.md
- 不修改设计文档
- 不修改前端代码
- 不修改 schema.py（FreshnessInfo 已在 Step1 添加）
