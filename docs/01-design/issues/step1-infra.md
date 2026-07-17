# Issue: Step 1 — 修复基础设施

type: fix + feat
design_ref: docs/01-design/v0.1.0-backend-design.md (第3-4节)
depends_on: none

## 目标

修复两个基础设施问题，为后续所有 Step 奠定基础：
1. CacheManager.db_get 的 SQLite 行解包错误
2. 新增 FreshnessInfo 协议，替换魔术字段传递

## 1. 修复 db_get 解包安全

**文件：** `src/diting/cache/cache_manager.py` 第 255-291 行

**当前代码问题：**
```python
# 当前：zip(cols, row) 在列数不匹配时默默产生错位数据
# 当 row 字段数 ≠ cols 长度时，zip 按较短者截断
return dict(zip(cols, row))
```

**修复为：**
```python
# 索引安全访问：按列名逐一取值，超界跳过而非截断
result = {}
for i, col in enumerate(cols):
    if i < len(row):
        result[col] = row[i]
return result
```

**验证：** 新增测试用例：单列表、空表、列数不匹配边界情况。

## 2. 新增 FreshnessInfo 数据类

**文件：** `src/diting/schema.py`

```python
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class FreshnessInfo:
    """数据新鲜度信息，在所有 API 响应中透传。"""
    data_time: datetime | None    # 数据产生时间（provider 返回的时间戳）
    source: str                   # 来源标识（mx-data / eastmoney / cache）
    is_fresh: bool                # 是否在有效期内
    age_seconds: float            # 数据年龄（秒）
    ttl_seconds: int              # 有效期（秒）
```

## 3. 重写 _api_response() 信封

**文件：** `src/diting/web/routes.py` 第 27-44 行

**当前：** 用魔术字段 `_cache_state` 在 dict 中隐式传递 → service 层和 route 层耦合

**修复：** `_api_response()` 新增 `freshness` 参数，不再从 data dict 中 pop 魔术字段：

```python
def _api_response(data, *, freshness=None, error=None):
    resp = {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    if freshness:
        resp["freshness"] = {
            "data_time": freshness.data_time.isoformat() if freshness.data_time else None,
            "source": freshness.source,
            "is_fresh": freshness.is_fresh,
            "age_seconds": freshness.age_seconds,
            "ttl_seconds": freshness.ttl_seconds,
        }
    if error:
        resp["error"] = error
    return resp
```

**兼容性：** 现有调用 `_api_response(data)` 不变，freshness 字段缺省时不出现在响应中。

## 验收标准

- [ ] pytest 全绿（包括新增测试）
- [ ] ruff check 零问题
- [ ] `curl /api/health` 返回的 JSON 结构不变
- [ ] `curl /api/dashboard` 返回的 JSON 结构不变（freshness 暂为空，Phase 2 接入）
- [ ] 新增 `test_cache_db_get_boundary.py` 测试覆盖列数不匹配场景

## 约束

- 不修改 AGENTS.md
- 不修改设计文档
- 不修改前端代码
- 不修改 pyproject.toml（版本保持 0.1.0）
