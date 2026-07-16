# 谛听 · 全页面可用性审视与设计

> 文档版本：v1.0 · 2026-07-11 · CodeWhale
> 审视范围：5 个前端页面 + 对应后端 API/服务层
> 基于源码：`frontend/js/app.js` (934行) + `src/diting/web/routes.py` (185行) + `src/diting/web/services.py` (590行)

---

## 总体评估

| 维度 | 状态 |
|------|:----:|
| 页面骨架完整度 | 🟡 5/5 页面都有渲染函数，骨架屏到位 |
| 后端 API 覆盖度 | 🟡 7 个 JSON 端点，但数据链路残缺（依赖 watchlist 非空） |
| 交互可用性 | 🔴 设置页零功能、仪表盘假数据、选股机会无列表 |
| 数据真实性 | 🔴 VMD gauge 硬编码 48、饼图硬编码、卡片信号全来自自选股评分 |
| 配置持久化 | 🔴 仅内存保存，重启即丢失 |

**总问题数：** 28 个（8 快速修复 + 20 架构改进）

---

## 页面1 — 仪表盘

### 审视意见

| # | 问题 | 严重度 | 源码证据 |
|:-:|:-----|:------:|:---------|
| D1 | 4 信号卡片数值来自空 watchlist，始终 `--` 或 0 | 🔴 P1 | `dashboardData?.buy_signals ?? '--'`（line 269-272）；后端 `get_dashboard_data()` 调用 `get_opportunities()` 依赖 `load_watchlist()` 非空 |
| D2 | VMD gauge 硬编码 `48`，无后端对接 | 🔴 P1 | `charts.renderVMDGauge('vmd-gauge', 48)`（line 320） |
| D3 | 信号分布饼图硬编码 `{买入:12, 关注:8, 观望:5, 回避:3}` | 🔴 P1 | `charts.renderPie('portfolio-pie', [{name:'买入',value:12}...])`（line 321-326） |
| D4 | 卡片不可点击下钻 → 无法看到哪些股票触发了信号 | 🟡 P2 | 卡片是 `<div class="stat-card">` 无 onclick |
| D5 | 无大盘指数概况（上证/深证/创业板） | 🟡 P2 | 仅 `get_market_sentiment()` 返回上证单一指数 |
| D6 | "最近信号"区域永远是 `暂无数据` | 🟡 P2 | 硬编码 `<p>暂无数据</p>`（line 314） |

### 后端设计方案

#### D1 — 信号卡片对接真实数据

**当前链路：**
```
get_dashboard_data()
  → get_opportunities()          # 依赖 watchlist
    → load_watchlist()            # → DB → 可能为空
      → repo.get_realtime()      # 批量取 4 只
        → 简单涨跌评分
  → buy/watch/hold/avoid 计数
```

**改进：增加大盘指数卡片作为兜底显示**

```python
# 新增：GET /api/dashboard → 丰富返回值
{
  "status": "ok",
  "market_indices": [            # 新增
    {"name": "上证指数", "code": "000001", "price": 3234.56, "change_pct": 0.23},
    {"name": "深证成指", "code": "399001", "price": 11234.78, "change_pct": -0.15},
    {"name": "创业板指", "code": "399006", "price": 2456.12, "change_pct": 0.67}
  ],
  "buy_signals": 3,
  "watch_signals": 5,
  "hold_signals": 2,
  "avoid_signals": 0,
  "top_opportunities": [         # 新增：top 5 自选股机会
    {"code": "002475", "name": "立讯精密", "score": 82, "rating": "buy"},
    ...
  ],
  "vmd_cycle": {                 # 新增：VMD 真实数据
    "index_code": "000001",
    "cycle_position": 62.5,
    "trend": "upward"
  }
}
```

**后端改动：**

- `services.py` `get_dashboard_data()`：
  1. 新增批量获取三大指数实时行情 `repo.get_realtime(["000001", "399001", "399006"])`
  2. 调用 `get_opportunities()` 取 top 5
  3. 新增 `_get_vmd_cycle()` 方法 → 对大盘指数跑 VMD 分解

- `routes.py`：无需改动，返回值扩展向后兼容

**快速修复 vs 架构改进：**
- **快速修复（D1+D5）：** 在 `get_dashboard_data()` 中加 3 个指数实时行情 + 返回 top 5 机会
- **架构改进（D4）：** 卡片可点击 → 需要新路由 `#/opportunities?filter=buy`，跳转到"选股机会"页面并预筛选

---

#### D2 — VMD 仪表盘对接后端

**VMD 数据流设计：**

```
GET /api/dashboard
  → get_dashboard_data()
    → _get_vmd_cycle("000001", days=120)   # 新方法
      → repo.get_historical("000001", ...)  # 上证 120 天日线
      → VMDDecomposer.decompose(close)       # K=6, alpha=2000
      → 计算 cycle_position (0-100)
      → 计算 trend_slope
```

**信号层已有 `src/diting/signals/vmd.py`，可直接复用：**

```python
# services.py 新增方法
def _get_vmd_cycle(self, index_code: str = "000001", days: int = 120) -> dict:
    """计算大盘 VMD 周期位置"""
    historical = self.get_historical(index_code, days=days)
    if not historical:
        return {"position": 50.0, "trend": "unknown"}
    try:
        from ..signals.vmd import VMDDecomposer
        close = historical.df["收盘"].values.astype(float)
        vmd = VMDDecomposer(k=6, alpha=2000)
        u, _, _ = vmd.decompose(close)
        # u[-1] 是最低频分量（趋势），计算其相位位置
        trend = u[-1]
        position = (trend[-1] - trend.min()) / (trend.max() - trend.min()) * 100
        trend_direction = "upward" if trend[-1] > trend[-20] else "downward"
        return {"position": round(float(position), 1), "trend": trend_direction}
    except Exception:
        return {"position": 50.0, "trend": "unknown"}
```

**前端改动：**

```javascript
// renderDashboard() 中替换硬编码
const vmdPos = dashboardData?.vmd_cycle?.position ?? 50;
charts.renderVMDGauge('vmd-gauge', vmdPos);

// 饼图用真实数据
const pieData = [
  { name: '买入', value: buyCount },
  { name: '关注', value: watchCount },
  { name: '观望', value: holdCount },
  { name: '回避', value: avoidCount },
];
charts.renderPie('portfolio-pie', pieData, '信号分布');
```

**分类：架构改进**（涉及 VMD 信号计算 + 新 API 字段）

---

#### D3 — 饼图使用真实数据

**与 D1 联动：** 饼图数据源从硬编码改为 `dashboardData` 的 `buy_signals` 等字段。

**分类：快速修复**（纯前端改 3 行）

---

#### D4 — 卡片点击下钻

**设计：** 4 个信号卡片可点击 → 跳转到选股机会页面并预置筛选条件

```
点击"买入信号"卡片
  → window.location.hash = '#/opportunities?filter=buy'
  → renderOpportunities() 读取 ?filter=buy
  → 只显示 score >= 75 的股票列表
```

**前端改动：**
- 4 个 stat-card 加 `onclick` 和 `style="cursor:pointer"`
- `renderOpportunities()` 读取 `window.location.search` 中的 `filter` 参数

**分类：架构改进**（需在选股机会页面先有列表 → 见页面3设计）

---

#### D5 — 大盘指数概况

**与 D1 联动：** 新增 `market_indices` 字段，前端加 3 个迷你指数卡片

**前端改动：**
```html
<div class="index-mini-row">
  <div class="index-mini">上证 3234.56 <span style="color:#00b894">+0.23%</span></div>
  <div class="index-mini">深证 11234.78 <span style="color:#e17055">-0.15%</span></div>
  <div class="index-mini">创业板 2456.12 <span style="color:#00b894">+0.67%</span></div>
</div>
```

**分类：快速修复**（数据已在 D1 的后端改动中返回）

---

#### D6 — 最近信号列表

**设计：** 展示最近分析过的股票信号（从 `get_opportunities()` 的 top 5 或本地记录）

**后端改动：**
- `get_dashboard_data()` 返回 `recent_signals` 字段：从 `get_opportunities()` 取前 5
- 每条含 `{code, name, score, rating, change_pct}`

**分类：快速修复**（复用已有 `get_opportunities()` 数据）

---

## 页面2 — 个股分析

### 审视意见

| # | 问题 | 严重度 | 源码证据 |
|:-:|:-----|:------:|:---------|
| S1 | 引擎评分仅有 verdict（规则引擎），AI 引擎因 Key 未配不可用 | 🔴 P1 | `engine_names = discover_engines()[:3]`（services.py line 312），`get_llm()` 读环境变量，服务器未配 → 超时 |
| S2 | 搜索框无自动补全/历史记录 | 🟡 P2 | `_bindSearch()` 仅做正则验证 + 跳转 |
| S3 | K 线默认 250 天数据量，移动端 167 点蜡烛图过密 | 🟢 P3 | `get_historical(code, days=250)`，前端无采样 |
| S4 | 多空理由分类粗糙：仅靠关键词匹配 | 🟡 P2 | `bull_reasons/bear_reasons` 靠 `"买入"/"看空"` 等关键词分类（services.py line 339-356） |

### 后端设计方案

#### S1 — AI 引擎可用性

**根因：** 已在 v0.4.2 的 `resolve-deepseek-api-key-design.md` 中设计。

**当前状态：** `get_llm()` 已改为读 `AI_API_KEY` 环境变量（v0.4.2），服务器需部署 `/etc/diting/env`。

**建议补充：** 无 Key 时的自动降级（已在 resolve 文档的方案 B 中提出，未实现）：

```python
# services.py analyze_stock() 中
engine_names = discover_engines()
# 如果没有 AI Key，跳过 AI 引擎
import os
if not os.environ.get("AI_API_KEY"):
    engine_names = [n for n in engine_names
                    if n not in ("buffett", "can_slim", "wyckoff")]
    logger.info("services.no_ai_key", engines=engine_names)
```

**分类：架构改进**（需部署配合 + 降级逻辑）

---

#### S2 — 搜索自动补全

**设计：** 新增 `GET /api/search/suggest?q={prefix}` 端点

```python
@router.get("/api/search/suggest")
async def api_search_suggest(q: str = ""):
    """股票代码/名称模糊搜索建议"""
    results = service.search_suggest(q)
    return {"results": results}
```

**后端实现（services.py）：**

```python
def search_suggest(self, q: str) -> list[dict]:
    """从自选股 + 本地股票列表模糊匹配"""
    results = []
    # 1. 自选股优先
    db = WatchlistDB()
    for row in db.list():
        if q in row["code"] or q in row["name"]:
            results.append({"code": row["code"], "name": row["name"], "source": "watchlist"})
    # 2. 上证/深证前 500 只常见股票（可缓存到本地 JSON）
    # ... 后续扩展
    return results[:8]
```

**前端改动：**
- 搜索输入框加 `oninput` 事件 → 展示下拉建议列表
- 点击建议 → 填充代码 + 跳转

**分类：架构改进**（需新 API + 股票代码库）

---

#### S3 — K 线数据采样

**当前：** 250 天全量数据传给前端，ECharts 渲染全部蜡烛图

**改进：** 移动端/数据量 > 120 天时自动降采样

```javascript
// charts.js renderKline() 中
function downsample(data, maxPoints = 120) {
  if (data.dates.length <= maxPoints) return data;
  const step = Math.ceil(data.dates.length / maxPoints);
  return {
    dates: data.dates.filter((_, i) => i % step === 0),
    ohlc: data.ohlc.filter((_, i) => i % step === 0),
    // ...
  };
}
```

**分类：快速修复**（纯前端优化）

---

#### S4 — 多空理由分类

**当前：** 靠关键词列表 `["买入","看多","低估"...]` vs `["卖出","看空","高估"...]`。

**问题：** 引擎 narrative 中没有这些词的信号会被漏掉。

**改进方案 A（快速）：** 扩充关键词列表，增加兜底分类

```python
# 如果既不在 bull_kw 也不在 bear_kw → 归入 neutral_reasons
neutral_reasons.append(line[:60])
```

**改进方案 B（架构）：** 引擎返回结构化 signals（已在 schema 中定义但不强制使用），用 `AnalysisResult.signals` 替代 narrative 解析。

**分类：快速修复（方案 A）/ 架构改进（方案 B）**

---

## 页面3 — 选股机会

### 审视意见

| # | 问题 | 严重度 | 源码证据 |
|:-:|:-----|:------:|:---------|
| O1 | 只有 4 个统计卡片 + 空状态提示，无实际股票列表 | 🔴 P1 | `renderOpportunities()` line 660-665 永远渲染 empty-state |
| O2 | 数据完全依赖自选股非空 | 🔴 P1 | `get_opportunities()` 第 493 行 `if not stocks: return []` |
| O3 | 评分算法极简（仅涨跌幅），无技术指标 | 🟡 P2 | line 518-531：`change_pct > 3 → +10`, `change_pct < -3 → -10` |
| O4 | 无市场热点/板块轮动数据（无自选股时无任何内容） | 🟡 P2 | `get_opportunities()` 只有自选股路径 |

### 后端设计方案

#### O1+O2 — 从"统计数字"到"股票列表"

**重新定位：** "选股机会"页面应展示：
1. 自选股中有评分排序的股票列表（有自选股时）
2. 指定市场/板块的快速扫描结果（无自选股时）
3. 统计卡片作为汇总，下方是带评分的股票列表

**API 改造：**

```python
# GET /api/opportunities → 返回结构增强
{
  "total": 8,
  "strong_buy": 2,
  "watch": 3,
  "hold": 2,
  "avoid": 1,
  "items": [                       # 新增：股票列表
    {
      "code": "002475",
      "name": "立讯精密",
      "price": 32.45,
      "change_pct": 3.21,
      "score": 82,
      "rating": "buy",
      "signals": ["强势上涨", "RSI 金叉"]
    },
    ...
  ]
}
```

**后端改动（services.py）：**

```python
def get_opportunities(self) -> dict:
    # 现有逻辑保持不变，但返回 dict 而非 list
    items = self._scan_opportunities()  # 原逻辑
    return {
        "total": len(items),
        "strong_buy": sum(1 for i in items if i["score"] >= 75),
        "watch": sum(1 for i in items if 55 <= i["score"] < 75),
        "hold": sum(1 for i in items if 35 <= i["score"] < 55),
        "avoid": sum(1 for i in items if i["score"] < 35),
        "items": items,
    }
```

**前端改动（renderOpportunities）：**
- 在统计卡片下方渲染可滚动的股票列表
- 每行：代码 | 名称 | 价格 | 涨跌 | 评分 | 评级标签
- 点击行 → 跳转 `#/stock/{code}`

```javascript
// renderOpportunities() 中，统计卡片后加列表
if (oppData?.items?.length > 0) {
  let listHtml = '<div class="card" style="padding:0;overflow:hidden"><table>...';
  for (const item of oppData.items) {
    listHtml += `<tr class="watchlist-row" data-code="${item.code}">
      <td>${item.code}</td><td>${item.name}</td>...
      <td><span class="tag tag-${item.rating}">${item.rating}</span></td>
    </tr>`;
  }
  listHtml += '</table></div>';
}
```

**分类：架构改进**（API 返回结构变更 + 前端列表渲染）

---

#### O3 — 评分增强

**当前评分：** 仅基于 `change_pct` 加减分 → 太简陋

**改进：** 加入快速技术指标（不需要 AI 引擎）

```python
def _fast_score(self, code: str, quote) -> int:
    """快速评分：涨跌幅 + 量比 + RSI（可选）"""
    score = 50
    # 涨跌幅
    if quote.change_pct > 3: score += 15
    elif quote.change_pct > 1: score += 8
    elif quote.change_pct < -3: score -= 15
    elif quote.change_pct < -1: score -= 8
    # 量比（如果有）
    # todo: 获取量比数据
    return max(0, min(100, score))
```

**分类：快速修复**（扩展已有评分逻辑）

---

#### O4 — 无自选股时的市场热点

**方案：** 当 `load_watchlist()` 为空时，扫描常见指数成分股（如上证 50/沪深 300 前 20 只）

```python
def _get_fallback_universe(self) -> list[str]:
    """无自选股时的兜底股票池"""
    FALLBACK_CODES = [
        "600519", "000858", "002475", "300750", "601318",
        "600036", "000333", "601166", "600276", "002415",
        # 沪深 300 前 20 只按市值排序
    ]
    return FALLBACK_CODES
```

**分类：架构改进**（需内置股票池 + 可能增加 API 调用量）

---

## 页面4 — 自选股

### 审视意见

| # | 问题 | 严重度 | 源码证据 |
|:-:|:-----|:------:|:---------|
| W1 | 添加时名称需手动输入，无自动补齐 | 🟡 P2 | `placeholder="名称(可选)"`（line 718），无模糊查询 |
| W2 | 删除无撤销机制 | 🟡 P2 | `confirm('确定删除自选股？')` 后直接调 DELETE（line 801-806） |
| W3 | 无编辑功能 | 🟢 P3 | 表结构有 `tags` 字段但前端未使用 |
| W4 | 无批量删除/导入/导出 | 🟢 P3 | 无对应 UI |
| W5 | 价格字段可能为 null（实时行情获取失败时） | 🟡 P2 | `_fmt(item.price, 2)` 在 null 时显示 `-` |

### 后端设计方案

#### W1 — 名称自动补齐

**利用后端实时行情接口：** 输入代码 → 失焦或延迟 300ms → 查询实时行情 → 自动填名称

```javascript
// _bindWatchlistAdd() 增强
addInput.addEventListener('blur', async () => {
  const code = addInput.value.trim();
  if (!/^\d{6}$/.test(code)) return;
  const nameInput = document.getElementById('wl-add-name');
  if (nameInput.value) return; // 已有值则不覆盖
  // 查实时行情取名称
  const res = await api.stock(code);
  if (res.ok && res.data?.name) {
    nameInput.value = res.data.name;
    showStatus('✅ 已识别：' + res.data.name);
  }
});
```

**分类：快速修复**（纯前端优化 + 复用已有 `/api/stock/{code}`）

---

#### W2 — 删除撤销

**设计：** 删除后 5 秒内显示"已删除，点击撤销"提示条

```javascript
let _undoDelete = null;  // {code, name, timer}

function _doDelete(code, name) {
  await api.removeWatchlist(code);
  _undoDelete = { code, name, timer: setTimeout(() => { _undoDelete = null; }, 5000) };
  showStatus(`已删除 ${name}，<a href="javascript:void(0)" onclick="_undoLastDelete()">撤销</a>`);
  renderWatchlist();
}

async function _undoLastDelete() {
  if (!_undoDelete) return;
  await api.addWatchlist(_undoDelete.code, _undoDelete.name);
  _undoDelete = null;
  renderWatchlist();
}
```

**后端：** 无需改动（已有 `add/remove` API）

**分类：快速修复**（纯前端优化）

---

#### W3 — 批量操作

**设计：** 表头加全选 checkbox，每行加勾选框，底部出现批量操作栏

**后端改动：** 新增 `POST /api/watchlist/batch-delete` + `POST /api/watchlist/batch-import`

```python
@router.post("/api/watchlist/batch-delete")
async def api_watchlist_batch_delete(request: Request):
    body = await request.json()
    codes = body.get("codes", [])
    service.batch_remove_watchlist(codes)
    return {"status": "ok", "deleted": len(codes)}
```

**分类：架构改进**（需新 API + 前端批量交互）

---

## 页面5 — 设置

### 审视意见

| # | 问题 | 严重度 | 源码证据 |
|:-:|:-----|:------:|:---------|
| T1 | 所有开关硬编码 on/off，无交互逻辑 | 🔴 P1 | `{ label: '...', on: true, ... }` 写死在 renderSettings 中（line 849-888） |
| T2 | 保存按钮弹出 `alert('配置保存将在后续版本实现')` | 🔴 P1 | line 926 |
| T3 | 配置不持久化，`save_settings()` 只存内存 | 🔴 P1 | `self._settings = data`（services.py line 583），重启丢失 |
| T4 | 开关切换影响到底层行为未设计 | 🔴 P1 | 无链路：前端 toggle → POST `/api/settings` → 影响 `_build_repo()` / `get_llm()` / pipeline |

### 后端设计方案

#### 重新思考：哪些设置真正值得暴露给用户？

**用户应该控制的：**

| 设置 | 理由 | 实现方式 |
|------|------|---------|
| AI 模型选择 | 不同模型成本/速度不同 | 影响 `get_llm()` 的 model 参数 |
| 通知渠道开关 | 不同用户偏好不同 | 影响 notifier 初始化 |
| ~~数据源开关~~ | 系统应自动降级，不应让用户手动开关 | 自动降级链已实现 |

**系统应自动处理的：**
- 数据源降级：`eltdx → ashare → mx-data → akshare` 自动检测可用性
- 引擎降级：AI Key 不可用时自动跳过 AI 引擎

---

#### T1+T2+T3 — 让设置可用

**存储方案：** 使用已有 `WatchlistDB` 数据库，新增 `settings` 表

```sql
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

```python
# storage.py 新增
class SettingsDB:
    def get(self, key: str, default: str = "") -> str: ...
    def set(self, key: str, value: str) -> None: ...
    def get_all(self) -> dict: ...
```

**后端改动：**

1. `services.py` `save_settings()` → 写入 DB

```python
def save_settings(self, data: dict) -> dict:
    settings_db = SettingsDB()
    for k, v in data.items():
        settings_db.set(k, str(v))
    self._apply_settings(data)  # 实时生效
    return {"status": "ok"}
```

2. `services.py` 新增 `_apply_settings()` → 影响运行时行为

```python
def _apply_settings(self, data: dict) -> None:
    # AI 模型切换
    if "ai_model" in data:
        from ..ai.client import reset_llm
        reset_llm(model=data["ai_model"])
    # 引擎开关
    if "engines" in data:
        # 存到实例变量，analyze_stock() 读取
        self._settings["engines"] = data["engines"]
    # 通知渠道
    if "notify" in data:
        self._settings["notify"] = data["notify"]
```

3. `app.py` 启动时从 DB 加载配置

```python
@app.on_event("startup")
async def load_settings():
    settings_db = SettingsDB()
    service._settings = settings_db.get_all()
    service._apply_settings(service._settings)
```

**前端改动：**

```javascript
// renderSettings() → 所有 toggle 可交互
groups.forEach(g => {
  g.items.forEach(it => {
    it.el.querySelector('.toggle').addEventListener('click', () => {
      it.on = !it.on;
      // 更新 UI
    });
  });
});

// 保存按钮 → POST /api/settings
document.getElementById('settings-save').addEventListener('click', async () => {
  const data = _collectSettings();
  const res = await api.saveSettings(data);
  if (res.ok) showStatus('✅ 设置已保存');
  else showStatus('❌ 保存失败');
});
```

**分类：架构改进**（需 DB 表 + 前后端全链路）

---

#### 设计决策：简化设置页面

**当前 4 组设置 → 建议精简为 2 组：**

**保留：**
1. 🤖 AI 模型选择（单选：v4-pro / v4-flash）
2. 📬 通知渠道开关（飞书 / 邮件 / 本地）

**移除：**
- 数据源开关：系统自动降级，用户无需关心
- 引擎开关：加日志说明而非暴露开关

**分类：架构改进**（与上述设置实现耦合）

---

## 分类汇总

### 快速修复（8 项）

| # | 页面 | 描述 | 预计改动量 |
|:-:|:-----|:-----|:---------:|
| Q1 | 仪表盘 D3 | 饼图使用真实 dashboardData | 前端 3 行 |
| Q2 | 仪表盘 D5 | 大盘指数迷你卡片 | 前端 ~20 行 + 后端 ~20 行 |
| Q3 | 仪表盘 D6 | 最近信号列表 | 前端 ~15 行 + 后端 ~5 行 |
| Q4 | 个股 S3 | K 线移动端降采样 | 前端 ~20 行 (charts.js) |
| Q5 | 个股 S4 | 多空理由关键词扩充 + neutral | 后端 ~10 行 |
| Q6 | 选股 O3 | 扫描评分加入量比 | 后端 ~15 行 |
| Q7 | 自选 W1 | 名称自动补齐（失焦查行情） | 前端 ~20 行 |
| Q8 | 自选 W2 | 删除 5 秒撤销 | 前端 ~30 行 |

### 架构改进（15 项）

| # | 页面 | 描述 | 涉及模块 |
|:-:|:-----|:-----|:---------|
| A1 | 仪表盘 D1 | 信号卡片对接真实数据 + 增加 top_opportunities | services.py + routes.py + app.js |
| A2 | 仪表盘 D2 | VMD gauge 对接后端 real VMD 计算 | services.py + signals/vmd.py |
| A3 | 仪表盘 D4 | 卡片点击下钻 → 预筛选选股机会 | app.js（需 O1 先完成） |
| A4 | 个股 S1 | AI Key 不可用时自动降级跳过引擎 | services.py + ai/client.py |
| A5 | 个股 S2 | 搜索自动补全 API | routes.py + services.py + app.js |
| A6 | 选股 O1 | 选股机会页面展示股票列表 | services.py + app.js |
| A7 | 选股 O4 | 无自选股时扫描市场热点 | services.py |
| A8 | 自选 W3a | 批量删除 API | routes.py + services.py + storage.py |
| A9 | 自选 W3b | 批量导入 API（CSV/JSON） | routes.py + services.py + storage.py |
| A10 | 设置 T1 | 设置页面 toggle 可交互 | app.js |
| A11 | 设置 T2 | 保存按钮写 DB | services.py + storage.py（新增 settings 表） |
| A12 | 设置 T3 | 启动时从 DB 加载设置 | app.py + services.py |
| A13 | 设置 T4 | 设置生效链路（AI 模型切换） | ai/client.py（加 reset_llm） |
| A14 | 设置 T4 | 设置生效链路（引擎开关） | services.py analyze_stock() |
| A15 | 设置 | 精简设置页面（4组→2组） | app.js |

### 新增 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/search/suggest?q=` | 搜索自动补全 |
| POST | `/api/watchlist/batch-delete` | 批量删除自选股 |
| POST | `/api/watchlist/batch-import` | 批量导入自选股 |

### 新增存储表

```sql
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 实施建议

### 实施顺序

```
Phase 1（快速修复 · 立即）：Q1-Q8
  → 8 项改动，2-3 小时

Phase 2（仪表盘真实数据）：A1 + A2 + A3
  → VMD 计算 + 指数行情 + 卡片下钻

Phase 3（选股机会重构）：A6 + A7
  → 股票列表 + 兜底扫描

Phase 4（搜索体验 + 自选股完善）：A5 + A8 + A9
  → 自动补全 + 批量操作

Phase 5（设置可用）：A10-A15
  → 全链路设置 → 这是最大的一项改动
```

### 风险

| 风险 | 缓解 |
|------|------|
| VMD 计算复杂度高，仪表盘请求可能变慢 | cache vmd_cycle 结果，TTL 60s（日线一天一变） |
| 自选股批量操作并发安全 | `WatchlistDB` 已有 `threading.Lock` |
| 设置 DB 表新增需向后兼容 | `CREATE TABLE IF NOT EXISTS`，服务启动时自动建表 |
| 前端交互改动量大（尤其是设置页） | 分 Phase 渐进交付，每次只改 1-2 个页面 |

### 不涉及的范围

- 不修改 L0-L3 核心引擎层
- 不新增外部依赖（settings DB 复用已有 sqlite3）
- 不改变 CLI 接口
- 不改变前端路由表结构
