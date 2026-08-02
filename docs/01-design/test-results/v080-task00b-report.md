# v0.8.0 Task 00b 完成报告

## 结论

Task 00b 已完成。Windows 工作区的文本换行策略、pre-commit 作用域和核心测试门禁现在可重复执行；连续两次全量 pre-commit 均通过，第二次运行前后的 Git 状态哈希一致。

## 改动

- `.gitattributes`：全仓文本统一 LF，常见二进制格式显式标记为 binary。
- `.pre-commit-config.yaml`：Ruff lint/format 与发布门禁一致，只覆盖 `src/` 和 `tests/`。
- `tests/unit/test_project_hygiene.py`：增加换行策略与 Ruff hook 作用域断言。
- 历史文本文件：由 pre-commit 仅执行换行、尾空格和 EOF 的机械归一化；抽样 diff 未发现语义改动。
- `tests/integration/test_cli_smoke.py`：将会访问真实行情源的命令测试标记为 `network`，避免污染离线核心门禁。
- `src/diting/web/services/scan.py`：删除机会榜以未分析 `quick_score` 补位的旧回退路径，只保留已完成分析的结果。
- 本机损坏的旧 `.venv` 包元数据已移动到外部归档 `venv-stale/`，随后以 `uv sync --extra dev --link-mode copy` 重建；未删除用户数据。

## 验证结果

| 命令 | 结果 |
|---|---|
| `uv run pytest tests/unit/test_project_hygiene.py -q` | 20 passed |
| `uv run pre-commit run --all-files`（连续两次） | 全部 hooks passed |
| 第二次运行前后状态哈希 | 均为 `9e7a47f81d8ec996f0f37aeaad0c7f65dc4a5f71` |
| `uv run ruff check src/ tests/` | passed |
| `uv run ruff format --check src/ tests/` | 115 files formatted |
| `git diff --check` | passed |
| `node --check frontend/**/*.js` | 12 files passed |
| `uv run pytest tests/ -m "not network" -q --durations=10` | 475 passed, 79 deselected, 124.61s |

## 诊断记录

第一次完整测试达到 15 分钟上限，是因为旧 CLI smoke 测试未标记网络访问，且超时后外层进程未自动清理 Python 子进程。相关子进程已按 PID 和命令行精确终止。分层重跑结果为：

- unit：347 passed；
- integration：111 passed，36 deselected；
- e2e：17 passed，43 deselected。

集成测试最初还暴露了机会榜用 pending `quick_score` 补满 Top20 的真实语义错误；修复后集成层全绿。

## 已知风险

- 测试仍报告 FastAPI lifespan、SQLite 默认 timestamp converter 和部分信号处理参数的弃用/边界警告，后续迁移与 API 任务需要消除。
- 三个 watchlist CLI 测试各耗时约 9 秒，说明旧 CLI 仍有不必要的重型初始化；Task 03/21 会通过 bootstrap 与新版 CLI 收敛。
- 当前仅完成治理基线，Checkpoint C0 还需要 Task 01–03。
