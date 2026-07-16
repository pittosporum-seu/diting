# 谛听 · 缓存层设计 v2 — 完整版

> 2026-07-11 | 基于开源项目调研（Qlib/vnpy/freqtrade/QUANTAXIS）+ 自研需求

---

## 一、参考项目概览

| 项目 | Stars | 亮点 |
|------|:-----:|:------|
| **Qlib（微软）** | 15k | 因子缓存 + 二进制列存储 + LRU Cache |
| **vnpy** | 25k | 内存 dict 全量缓存 + 统一数据库抽象层 |
| **freqtrade** | 28k | SQLAlchemy + SQLite + 策略级缓存 |
| **QUANTAXIS** | 8k | MongoDB 时序存储 + 多级缓存 |
| **backtrader** | 14k | DataFeed 抽象，自定义存储插件 |

**核心共识：** 自部署单机工具不需要 Redis，Python dict + SQLite 就够用。

---

## 二、交易时段分类

### 🟢 盘中高频（9:30-11:30, 13:00-15:00）→ 内存 TTL 优先

| 数据 | 更新频率 | 推荐存储 | 说明 |
|:-----|:--------:|:---------|:-----|
| 自选股实时行情 | 30s-2min | 内存 dict + SQLite | 用户盯着看的 |
| 个股分析 | 2min | 内存 TTL | 含技术指标 + 评分 |
| 仪表盘 | 2min | 内存 TTL | 大盘指数 + 信号 |
| 大盘指数 | 2min | 内存 TTL | 上证/深证/创业板 |
| 市场情绪 | 5min | 内存 TTL | 涨跌比、量 |

### 🔵 盘后低频（非交易时段 / 每小时）→ SQLite 持久化

| 数据 | 更新频率 | 推荐存储 | 说明 |
|:-----|:--------:|:---------|:-----|
| 全市场行情快照 | 每小时 | SQLite `market_snapshot` 表 | ~5000 行 |
| 全市场扫描 Top 20 | 每日 1-2 次 | SQLite `market_scan_cache` 表 | 盘前+盘中 |
| 股票字典 | 每日 1 次 | SQLite `stock_dict` 表 | 代码/名称/拼音 |
| 历史 K 线 | 每日 1 次（收盘后） | SQLite `daily_kline` 表 | 日线数据 |

---

## 三、两层缓存架构

```
用户请求
    │
    ▼
┌──────────────────────────────────────────────┐
│  L1: 内存 TTLCache（热层）                     │
│  实时行情 / 个股分析 / 仪表盘                   │
│  TTLCache 实例，按数据类别分                     │
│  命中 → 直接返回（<1ms）                        │
│  未命中 → 查 L2                                │
├──────────────────────────────────────────────┤
│  L2: SQLite 持久缓存（冷层）                    │
│  全市场快照 / 扫描结果 / 股票字典                │
│  diting_cache.db，多表分区                      │
│  命中 → 返回 + 异步刷新（确保不 stale）           │
│  未命中 → 调 API → 写 L1+L2                    │
├──────────────────────────────────────────────┤
│  数据源 API（ashare / mx-data / akshare）       │
│  只有 L1 和 L2 都未命中时才调用                   │
└──────────────────────────────────────────────┘
```

---

## 四、SQLite 数据库设计

单个文件 `cache/diting_cache.db`，7 张表：

### 4.1 全市场行情快照

```sql
CREATE TABLE market_snapshot (
    code        TEXT PRIMARY KEY,
    name        TEXT,
    price       REAL,
    change_pct  REAL,
    open        REAL,
    high        REAL,
    low         REAL,
    volume      REAL,
    amount      REAL,
    turnover    REAL,
    updated_at  TIMESTAMP,
    batch_id    TEXT,
    INDEX idx_snapshot_batch (batch_id)
);
```
更新频率：盘中每小时，盘后不更新。数据源：ashare（新浪 API，每批 50 只）。

**注意：** ashare（新浪）不提供 PE/PB/market_cap 字段，这些估值指标需要通过 mx-data 单独查询。`market_snapshot` 只存新浪能提供的字段。

### 4.2 自选股高频缓存

```sql
CREATE TABLE watchlist_cache (
    code        TEXT PRIMARY KEY,
    name        TEXT,
    price       REAL,
    change_pct  REAL,
    high        REAL,
    low         REAL,
    volume      REAL,
    amount      REAL,
    score       INTEGER,
    updated_at  TIMESTAMP
);
```
更新频率：30s-2min。盘中走内存 TTL，盘后写回 SQLite。

### 4.3 个股分析缓存

```sql
CREATE TABLE stock_analysis_cache (
    code        TEXT PRIMARY KEY,
    result_json TEXT,
    updated_at  TIMESTAMP,
    expires_at  TIMESTAMP
);
```
更新频率：2min。含技术指标 + 评分 + 引擎结果。

### 4.4 仪表盘快照

```sql
CREATE TABLE dashboard_cache (
    id          INTEGER PRIMARY KEY DEFAULT 1,
    data_json   TEXT,
    updated_at  TIMESTAMP
);
```
更新频率：2min。单行，存大盘 + 信号 + Top 机会。

### 4.5 全市场扫描结果

```sql
CREATE TABLE market_scan_cache (
    batch_id    TEXT,         -- 如 '2026-07-11-morning'
    scan_date   TEXT,         -- '2026-07-11'
    scan_time   TEXT,         -- 'morning' / 'afternoon'
    top20_json  TEXT,
    updated_at  TIMESTAMP,
    PRIMARY KEY (batch_id)
);
```
更新频率：每日 1-2 次。数据源：ashare（新浪）扫 5000 只，过滤 ST/退/<2元，评分取 Top 20。

### 4.6 股票字典

```sql
CREATE TABLE stock_dict (
    code    TEXT PRIMARY KEY,
    name    TEXT,
    pinyin  TEXT,
    market  TEXT,          -- 'SH'/'SZ'/'BJ'
    status  TEXT           -- 'normal'/'ST'/'delisted'
);
```
更新频率：每日。静态数据，几乎不改。

### 4.7 缓存元数据

```sql
CREATE TABLE cache_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMP,
    expires_at  TIMESTAMP,
    tier        TEXT      -- 'hot'/'warm'/'cold'
);
```
通用 key-value 缓存，存不太频繁访问的配置/结果。

---

## 五、按天分区策略

参考 Qlib 的按交易日划分 + freqtrade 的 SQLite 方案：

```
market_snapshot:  WHERE batch_id = '2026-07-11'    ← 按 batch_id 查当日快照
market_scan:      WHERE scan_date = '2026-07-11'    ← 按日期查当日扫描
watchlist_cache:  TRUNCATE + 重建（盘中高频覆盖）     ← 重启即重建
stock_dict:       持久保留，不分区                    ← 静态数据
```

**清理策略：** cron job 每天凌晨删除 3 天前的 `market_snapshot` 和 7 天前的 `market_scan_cache`。

---

## 六、UI 设置页缓存开关

在设置页新增「缓存管理」区块：

```
┌─────────────────────────────────────────────┐
│  📦 缓存管理                                 │
│                                              │
│  启用缓存                    [开关] ● ON     │
│  高频缓存有效期               [下拉] 2分钟   │
│                                              │
│  ── 缓存统计 ──                              │
│  内存缓存: 87/128 条目                        │
│  数据库缓存: 3.2 MB                          │
│  最后更新: 今日 11:23                        │
│                                              │
│  [🗑️ 清除所有缓存]  [🔄 立即刷新]           │
└─────────────────────────────────────────────┘
```

---

## 七、实施建议（参考 Qlib/vnpy 的经验）

| 阶段 | 内容 | 优先级 |
|:----:|:-----|:------:|
| 1 | 创建 `cache/` 目录 + `CacheManager` 类（内存+SQLite 双写） | P0 |
| 1.5 | ashare 分批能力改造：`fetch_realtime` 支持每批 50 只 + 切片重试 | P0 |
| 2 | 全市场扫描：ashare 批量获取行情 → 过滤 ST/退/<2元 → 评分 → 写入 `market_snapshot` + `market_scan_cache` + `stock_dict` | P1 |
| 3 | 现有 TTLCache 接入 SQLite 持久层（`_realtime_cache`→`watchlist_cache`，`_dashboard_cache`→`dashboard_cache`） | P1 |
| 4 | 定时任务：盘中 snapshot 每小时、盘后 scan 每日 2 次 | P2 |
| 5 | UI 缓存管理页面 + 后端 stats API | P2 |

**关键避坑：**
- 不要 Redis（Qlib/backtrader 都不用，单机工具不需要）
- 不要 MongoDB（QUANTAXIS 用但过于复杂）
- SQLite 写并发问题：用 WAL 模式 + 单线程写
