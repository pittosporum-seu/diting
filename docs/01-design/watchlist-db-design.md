# 自选股数据库化设计

> 将 `watchlist.csv` 替换为 SQLite 数据库，内置用户隔离。

---

## 1. 动机

- CSV 文件缺失时系统降级为空列表，用户无法添加自选股
- 没有 API 支持从前端添加/删除自选股
- 后续多用户场景需要数据隔离

## 2. 方案

### 2.1 数据库

使用 Python 内置 `sqlite3`，零外部依赖。数据库路径：`~/.diting/diting.db`（用户目录，不受工作目录影响）。

### 2.2 表结构

```sql
CREATE TABLE IF NOT EXISTS watchlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL,          -- 6位股票代码，如 002475
    name       TEXT NOT NULL DEFAULT '', -- 股票名称（缓存）
    market     TEXT NOT NULL DEFAULT 'sz', -- sz/sh/bj
    tags       TEXT NOT NULL DEFAULT '',   -- 标签（如 "核心仓","卫星仓"）
    user_id    TEXT NOT NULL DEFAULT 'default',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(code, user_id)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
```

### 2.3 用户隔离策略

| 阶段 | 实现方式 | 用户标识来源 |
|------|---------|-------------|
| 当前单用户 | `user_id = 'default'` | 硬编码 |
| 未来多用户 | 从请求头/Token 提取 | `X-User-Id` / JWT |
| 未来用户系统 | 关联 users 表 | session/token |

### 2.4 新增模块

**`src/diting/storage.py`** — 数据库管理

```python
class WatchlistDB:
    """自选股数据库，自动建表，线程安全。"""

    def __init__(self, db_path: str | None = None):
        # 默认 ~/.diting/diting.db
        ...

    def list(self, user_id: str = "default") -> list[dict]: ...
    def add(self, code: str, name: str = "", market: str = "sz",
            user_id: str = "default") -> bool: ...
    def remove(self, code: str, user_id: str = "default") -> bool: ...
    def has(self, code: str, user_id: str = "default") -> bool: ...
    def count(self, user_id: str = "default") -> int: ...
```

### 2.5 迁移策略

首次启动时：
1. 检查数据库是否存在 → 不存在则建表
2. 检查 `config/watchlist.csv` 是否存在 → 存在则导入到 DB，标记已迁移
3. 之后 `Config.load_watchlist()` 读 DB 而非 CSV

### 2.6 Web API 扩展

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/watchlist` | 获取自选股列表（已有） |
| POST | `/api/watchlist` | 添加自选股 `{code, name, market}` |
| DELETE | `/api/watchlist/{code}` | 删除自选股 |

### 2.7 配置变化

`Config` 类新增：
- `load_watchlist()` 改为优先读 DB，CSV 兜底
- 新增 `migrate_from_csv()` 迁移方法

## 3. 影响范围

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `src/diting/storage.py` | **新增** | WatchlistDB 类 |
| `src/diting/config.py` | 修改 | load_watchlist 改为读 DB |
| `src/diting/web/routes.py` | 修改 | 新增 POST/DELETE 端点 |
| `src/diting/web/services.py` | 修改 | 对接 WatchlistDB |
| `tests/unit/test_config.py` | 修改 | 适配 DB 测试 |
| `tests/unit/test_storage.py` | **新增** | DB 单元测试 |

## 4. 不涉及

- 不修改现有 L0-L4 核心层
- 不新增外部依赖
- 不改变 CLI 接口
