# 谛听 · v0.3.0 前后端分离架构设计

> 前后端完全解耦：API 只出 JSON，前端纯静态文件通过 API 获取数据。
> 日期：2026-07-07 | 版本：v0.3.0 | 状态：设计阶段 🟡

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    nginx / 浏览器                        │
│                                                         │
│   ┌─────────────────┐       ┌──────────────────────┐   │
│   │   前端 (静态)     │       │   后端 API （纯JSON）  │   │
│   │   port 5173      │──────→│   port 8000           │   │
│   │   HTML+JS+CSS    │ fetch │   FastAPI              │   │
│   │   不依赖后端渲染    │←─────│   只返回JSON,不含HTML   │   │
│   └─────────────────┘       └──────────┬───────────┘   │
│                                        │                │
│                              Pipeline │ Consensus      │
│                              DataRepo │ Engines        │
│                                        │                │
│                              4级数据源降级链              │
└─────────────────────────────────────────────────────────┘

铁律：
- 后端永远不知道"页面"这个概念
- 前端永远不import Python代码
- 前后端唯一通信渠道 = HTTP fetch
```

---

## 二、后端：纯 REST API `/api/*`

### 路由表

| 方法 | 路径 | 认证 | 说明 |
|:----:|:-----|:----:|------|
| GET | `/api/health` | — | 健康检查 |
| GET | `/api/stock/{code}` | — | 个股完整分析 |
| GET | `/api/dashboard` | — | 仪表盘数据 |
| GET | `/api/watchlist` | — | 自选股列表 |
| GET | `/api/opportunities` | — | 选股机会 |
| GET | `/api/search?q=002475` | — | 搜索框自动补全 |
| POST | `/api/settings` | — | 保存配置 |

### 统一响应格式

```json
// 成功
{
  "ok": true,
  "data": { ... },
  "elapsed_ms": 729
}

// 错误
{
  "ok": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "未找到股票 999999"
  }
}
```

---

### 2.1 `GET /api/health`

```json
{
  "ok": true,
  "data": {
    "version": "0.3.0",
    "providers": {
      "eltdx": "healthy",
      "ashare": "healthy",
      "mx_data": "no_key",
      "akshare": "healthy"
    },
    "engines": ["verdict", "vmd_rsi", "volume_profile"],
    "cache_hits": 42
  }
}
```

---

### 2.2 `GET /api/stock/{code}`

参数：`?engines=verdict,vmd_rsi`（可选，默认从配置读取）

```json
{
  "ok": true,
  "data": {
    "code": "002475",
    "name": "立讯精密",

    "quote": {
      "price": 63.28,
      "change_pct": 0.64,
      "open": 62.54, "high": 64.90, "low": 62.00,
      "volume": 1370000,
      "turnover": 8710000000,
      "pe": 30.2, "pb": 4.8,
      "total_mv": 218500000000
    },

    "verdict": {
      "score": 78,
      "rating": "buy",
      "label": "建议买入",
      "emoji": "\uD83D\uDFE2",
      "confidence": 0.65,
      "bull_reasons": [
        {"rank": 1, "text": "VMD 周期触底 (0.15) — 反弹概率较大", "source": "vmd"},
        {"rank": 2, "text": "RSI 超卖 (28.3) — 短期有修复动力", "source": "rsi"},
        {"rank": 3, "text": "主力资金近3日净流入 +2.3亿", "source": "fund_flow"}
      ],
      "bear_reasons": [
        {"rank": 1, "text": "PE 30x 高于行业均值 25x", "source": "pe"},
        {"rank": 2, "text": "消费电子板块近期资金轮出", "source": "sector"}
      ]
    },

    "engines": [
      {"name": "verdict",        "display": "Verdict",       "score": 85, "rating": "strong_buy"},
      {"name": "vmd_rsi",        "display": "VMD+RSI",       "score": 72, "rating": "buy"},
      {"name": "volume_profile", "display": "Volume Profile", "score": 78, "rating": "buy"},
      {"name": "wyckoff",        "display": "Wyckoff",       "score": 45, "rating": "hold", "error": "AI 不可用"},
      {"name": "buffett",        "display": "Buffett",       "score": 40, "rating": "hold", "error": "AI 不可用"},
      {"name": "can_slim",       "display": "CANSLIM",       "score": 35, "rating": "reduce","error": "AI 不可用"}
    ],

    "technicals": {
      "rsi":    {"value": 28.3, "label": "超卖",   "side": "bull"},
      "macd":   {"value": -0.32,"label": "死叉",   "side": "bear"},
      "kdj":    {"k": 18.5, "d": 22.0, "j": 12.0, "label": "超卖", "side": "bull"},
      "boll":   {"position": 0.08, "label": "下轨支撑", "side": "bull"},
      "vmd":    {"position": 0.15, "label": "谷底区",   "side": "bull"},
      "volume": {"ratio": 0.85, "label": "缩量", "side": "neutral"}
    },

    "charts": {
      "dates":     ["2026-06-26","2026-06-27",...,"2026-07-07"],
      "kline":     [[68.0,71.5,66.5,68.0],[66.0,68.2,64.8,65.3],...],
      "vmd_trend": [68.0, 65.3, 70.4, 66.2, 60.9, 64.4, 62.9, 63.3, 61.2, 63.0],
      "boll_upper":[72.0, 70.5, 71.0, 69.5, 67.0, 68.0, 67.5, 67.0, 65.5, 68.0],
      "boll_lower":[62.0, 61.5, 62.0, 60.5, 58.0, 59.0, 58.5, 58.0, 56.5, 59.0],
      "rsi":       [55, 42, 38, 25, 22, 30, 28, 32, 29, 28.3]
    },

    "errors": [],
    "elapsed_ms": 729
  }
}
```

---

### 2.3 `GET /api/dashboard`

```json
{
  "ok": true,
  "data": {
    "market": {
      "index_name": "上证指数",
      "index_value": 3990.24,
      "change_pct": -0.85,
      "vmd": {"position": 0.35, "zone": "低位", "side": "bull"}
    },
    "summary": {
      "score": 68,
      "bull_count": 6, "bear_count": 3, "total": 9,
      "daily_pnl": -4920,
      "daily_pnl_pct": -2.6
    },
    "portfolio": [
      {"code": "603667", "name": "五洲新春", "weight": 45, "score": 81},
      {"code": "002475", "name": "立讯精密", "weight": 20, "score": 78},
      {"code": "511980", "name": "金科ETF",  "weight": 15, "score": 35},
      {"code": "159770", "name": "机器人ETF","weight": 12, "score": 52},
      {"code": "603659", "name": "璞泰来",   "weight": 8,  "score": 55}
    ],
    "recent_signals": [
      {"code":"002475","type":"vmd_trough","strength":"high","time":"10:32"},
      {"code":"603667","type":"macd_golden","strength":"medium","time":"09:45"}
    ]
  }
}
```

---

### 2.4 `GET /api/watchlist`

```json
{
  "ok": true,
  "data": {
    "updated": "2026-07-07T15:00:00",
    "stocks": [
      {
        "code":"603667","name":"五洲新春","price":65.76,"change_pct":4.21,
        "score":81,"rating":"buy","label":"建议买入","emoji":"\uD83D\uDFE2",
        "vmd":{"position":0.25,"zone":"低位"},"rsi":52
      },
      {
        "code":"002475","name":"立讯精密","price":63.28,"change_pct":0.64,
        "score":78,"rating":"buy","label":"建议买入","emoji":"\uD83D\uDFE2",
        "vmd":{"position":0.15,"zone":"谷底"},"rsi":28
      }
    ]
  }
}
```

---

### 2.5 `GET /api/opportunities`

参数：`?min_score=30&limit=50&sort=score`

```json
{
  "ok": true,
  "data": {
    "counts": {"vmd_trough":23,"rsi_oversold":18,"rsi_overbought":12,"vmd_peak":4},
    "stocks": [
      {
        "code":"002475","name":"立讯精密","score":78,
        "rating":"buy","label":"建议买入","emoji":"\uD83D\uDFE2",
        "signals":[{"type":"vmd_trough","label":"VMD谷底"},{"type":"rsi_oversold","label":"RSI超卖"}],
        "fund_flow":"流入 2.3亿"
      }
    ]
  }
}
```

---

### 2.6 `GET /api/search`

参数：`?q=0024`

```json
{
  "ok": true,
  "data": {
    "results": [
      {"code":"002475","name":"立讯精密","type":"stock"},
      {"code":"002472","name":"双环传动","type":"stock"}
    ]
  }
}
```

---

### 2.7 `POST /api/settings`

```json
// Request
{
  "providers": {"primary": "eltdx"},
  "ai": {"model": "deepseek/deepseek-v4-pro"},
  "engines": ["verdict","vmd_rsi","volume_profile"],
  "notify": {"channel":"local"}
}

// Response
{"ok": true, "data": {"saved":true}}
```

---

### 后端错误码

| 错误码 | HTTP | 含义 | 前端展示 |
|:-------|:----:|:-----|:--------|
| `NOT_FOUND` | 404 | 股票不存在 | 搜索框高亮 + 提示 |
| `DATA_UNAVAILABLE` | 503 | 数据源全挂 | 重试按钮 + 倒计时 |
| `TIMEOUT` | 504 | 分析超时 | 部分结果 + 降级提示 |
| `INVALID_PARAM` | 400 | 参数错误 | 前端校验拦截 |
| `UNAUTHORIZED` | 401 | API Key 过期 | 跳转设置页 |
| `INTERNAL` | 500 | 后端异常 | 通用错误卡片 |

---

## 三、前端：SPA 单页应用

### 技术选型

| 选项 | 决策 | 理由 |
|:-----|:----:|------|
| 框架 | 原生 JS | 零依赖，体积小，降低入口门槛 |
| 路由 | hash-based | `/stock/002475` 用 hash 切换，不刷新页面 |
| 图表 | ECharts 5.5 CDN | 已有经验，309KB |
| 样式 | CSS 内联 | 无构建工具，一个 HTML 包含全部 |
| 状态 | 全局 object | 简单场景不需要 Vue/React |
| API | fetch | 原生浏览器 API |

### 文件结构

```
frontend/
├── index.html          ← SPA 入口，唯一的 HTML
├── css/
│   └── styles.css      ← 全部样式
├── js/
│   ├── app.js          ← 路由 + 全局状态
│   ├── api.js          ← API 调用封装
│   ├── charts.js        ← ECharts 图表渲染
│   └── pages/
│       ├── dashboard.js    ← 仪表盘页面逻辑
│       ├── analysis.js     ← 个股分析页面逻辑
│       ├── opportunities.js← 选股机会页面逻辑
│       └── settings.js     ← 设置页面逻辑
└── assets/
    └── echarts.min.js  ← 可内联或 CDN
```

### 前端状态管理

```javascript
// app.js — 全局状态
const STATE = {
  page: 'dashboard',          // 当前页面
  theme: 'light',             // 主题
  config: {},                 // 配置（启动时从 /api/health 加载）

  // 缓存（避免重复请求）
  stockCache: {},             // { code: { data, timestamp } }
  dashboardCache: null,
  watchlistCache: null,
};
```

### 路由设计（hash-based）

```
#dashboard           → 仪表盘
#stock/002475        → 个股分析
#stock/002475?l2     → 深度分析
#opportunities       → 选股机会
#watchlist           → 自选股
#settings            → 设置
```

---

## 四、时序图

### 4.1 个股分析（前后端分离版）

```
前端            后端 API                              数据源
 │                │                                     │
 │ hash=#stock/002475                                   │
 │                │                                     │
 │ 显示 loading   │                                     │
 │                │                                     │
 │ fetch /api/stock/002475                              │
 │───────────────→│                                     │
 │                │  MarketDataRepository.get_realtime() │
 │                │────────────────────────────────────→│
 │                │← quote + name                       │
 │                │                                     │
 │                │  Pipeline.run([context])            │
 │                │  ├─ VerdictEngine.analyze()         │
 │                │  ├─ VMDRSIEngine.analyze()          │
 │                │  └─ VolumeProfileEngine.analyze()   │
 │                │                                     │
 │                │  ConsensusEngine.fuse()             │
 │                │                                     │
 │   JSON 200     │                                     │
 │←───────────────│                                     │
 │                │                                     │
 │ 解析 JSON      │                                     │
 │ 渲染结论卡     │                                     │
 │ 渲染 K 线图    │                                     │
 │ 渲染引擎评分   │                                     │
 │ 渲染技术指标   │                                     │
 │                │                                     │
 │ 展示完成       │                                     │
```

### 4.2 仪表盘加载

```
前端                        后端 API
 │                            │
 │ 页面加载                    │
 │                            │
 │ GET /api/health            │
 │───────────────────────────→│
 │← version, providers       │
 │                            │
 │ GET /api/dashboard         │
 │───────────────────────────→│
 │← market, summary,         │
 │   portfolio, signals      │
 │                            │
 │ 渲染 4 统计卡片            │
 │ 渲染 VMD 仪表盘           │
 │ 渲染 持仓饼图             │
 │ 渲染 信号列表             │
```

---

## 五、部署方式

### 开发环境

```bash
# 终端 1：启动后端 API
diting api --port 8000

# 终端 2：启动前端（静态文件服务）
cd frontend && python -m http.server 5173
```

### 生产环境

```bash
# 用 fastapi.staticfiles 挂载前端
diting serve --port 8000
# → API on :8000/api/*
# → 前端 on :8000/ (static)
```

### Docker

```dockerfile
COPY src/diting/ /app/
COPY frontend/ /app/frontend/
CMD ["uvicorn", "diting.web.api:app", "--host", "0.0.0.0", "--port", "80"]
```

---

## 六、与旧版（server-rendered）对比

| 维度 | 旧版 Jinja2 SSR | 新版 前后端分离 |
|:-----|:--------------|:--------------|
| API 可测试性 | 只能端到端 | 每个接口独立 curl |
| 前端可独立部署 | ❌ 依赖 Python | ✅ 纯静态文件 |
| 开发并行度 | 前后端耦合 | 各自独立开发 |
| 首屏速度 | 快（服务端渲染） | 略慢（需JS渲染） |
| SEO | ✅ 服务端渲染 | ❌ SPA |
| 复杂度 | 低（模板直接配） | 中（需 JS 开发） |

结论：谛听是个人工具，不需要 SEO，前后端分离收益更大——**可独立测试、可并行开发、可跨端复用 API**。

---

## 七、实施计划

### Phase 1: API 层（后端）— 2天

| # | 交付 | 验证 |
|:-:|------|------|
| 1 | `web/api.py` + `web/routes.py` | `curl localhost:8000/api/health` |
| 2 | `GET /api/stock/{code}` 实现 | `curl localhost:8000/api/stock/002475` 返回 JSON |
| 3 | `GET /api/dashboard` + `watchlist` + `opportunities` | 逐接口验证 |

### Phase 2: 前端框架 — 1天

| # | 交付 | 验证 |
|:-:|------|------|
| 4 | `frontend/index.html` + `app.js` 路由框架 | 浏览 `/#stock/002475` 看到页面骨架 |
| 5 | `api.js` API 封装 | fetch 调通后端 |

### Phase 3: 前端页面 — 2天

| # | 交付 | 验证 |
|:-:|------|------|
| 6 | 个股分析页（结论卡+K线+引擎评分+技术指标） | 真实数据渲染 |
| 7 | 仪表盘页（大盘VMD+持仓分布+信号列表） | 真实数据渲染 |
| 8 | 自选股+选股机会+设置页 | 真实数据渲染 |

### Phase 4: 体验优化 — 1天

| # | 交付 | 验证 |
|:-:|------|------|
| 9 | 错误状态处理（loading/error/empty） | 断网测试 |
| 10 | 集成 + 测试 | `diting serve` 一键启动 |

---

## 八、新文件清单

```
src/diting/web/
├── __init__.py
├── app.py            ✏️ 重写：注册api路由，挂载静态前端
├── api.py            🆕 核心：6个JSON接口实现
├── routes.py         🆕 路由注册
└── services.py       🆕 业务编排层

frontend/             🆕 全新：纯静态前端
├── index.html        🆕 SPA入口
├── css/styles.css    🆕 全局样式
├── js/
│   ├── app.js        🆕 路由+状态管理
│   ├── api.js        🆕 API封装
│   ├── charts.js     🆕 ECharts渲染
│   └── pages/
│       ├── dashboard.js    🆕
│       ├── analysis.js     🆕
│       ├── opportunities.js🆕
│       └── settings.js     🆕
└── assets/
    └── echarts.min.js      (CDN)
```

---

*文档维护：小爪 | 谛听项目组 | 2026-07-07*
*版本：v0.3.0 | 状态：设计阶段 🟡 | 前后端分离架构*
