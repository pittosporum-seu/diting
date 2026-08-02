# v0.8.0 Checkpoint C0

## 状态

通过。v0.8 的版本、配置、领域协议、外部 Ports 和组合根已经形成可运行基础。

## 关键结果

- 版本：`0.8.0`，唯一来源 `pyproject.toml`。
- 配置：冻结、严格、密钥隔离，优先级 CLI overrides > environment > YAML > defaults。
- 数据语义：`DataResult[T]` 包含 data_time、cache_info、provider_traces、warnings、request_hash。
- 分析语义：失败不产生中性评分。
- 依赖：CLI 的具体 Provider 构造已迁入 bootstrap，Web 遗留绕过点受 AST 白名单约束。

## 门禁结果

- `uv run pytest tests/ -m "not network" -q --durations=10`：499 passed，79 deselected，143.15s。
- C0 聚焦兼容回归：94 passed，13 deselected。
- `uv run ruff check src/ tests/`：通过。
- `uv run ruff format --check src/ tests/`：123 files already formatted。
- `node --check frontend/**/*.js`：12 files passed。
- `uv run pre-commit run --all-files`：连续两次通过，状态哈希均为 `02e2a72e5de14591c4c73324ae9145df37f8ef31`。
- `git diff --check`：通过。

## 剩余风险

- Web 仍有两个具体 Provider import 例外；C1/Task 09 清零。
- 旧缓存表与新双数据库迁移尚未建立；C1 完成前不允许发布。
- FastAPI `on_event`、SQLite timestamp converter 和部分数值算法测试仍有 warnings。
- 单个引擎回归测试耗时约 60 秒，需在 C2 重构执行计划时降低。
