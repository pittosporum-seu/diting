# Contributing to Diting v0.8

先阅读 [AGENTS.md](AGENTS.md)、当前 Issue 和
[Accepted 总体设计](docs/01-design/v0.8.0-system-design.md)。设计、实现、测试、文档和发布
必须描述同一个系统。

## 开发环境

```bash
uv sync --extra dev
uv run pre-commit install
```

Python 最低版本为 3.12，依赖以 `pyproject.toml` 与 `uv.lock` 为准。不要提交 `.env`、数据
库、原始研究 CSV/PKL、报告或缓存。

## 改动流程

1. 从受保护集成分支创建 `codex/`、`feature/` 或 `fix/` 分支。
2. 在 Issue 中写清设计引用、修改范围、失败语义和验收标准。
3. 做最小纵向切片；保持 `interfaces → application → domain/ports` 依赖方向。
4. 核心数据只能通过 Data Gateway，分析只能通过 AnalysisOrchestrator，排名只能加载
   active 策略。
5. 同时提交聚焦测试和受影响文档；不要修改设计来迁就实现缺陷。
6. 运行完整门禁并在 PR 中记录原始结果和仍存在的风险。

## 必过门禁

```bash
uv run pre-commit run --all-files
uv run ruff check src/ tests/ browser_tests/ scripts/validate-api.py
uv run ruff format --check src/ tests/ browser_tests/ scripts/validate-api.py
uv run pytest tests/ -m "not network" -q
uv run python scripts/validate-api.py --check
find frontend -type f -name '*.js' -print0 | xargs -0 -n1 node --check
find scripts -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
uv run pytest browser_tests/ -q
```

网络测试允许独立运行和报告波动；研究策略晋升不能跳过完整数据与 OOS 门槛。禁止
`--no-verify`，发布控制器也没有跳过测试的参数。

## Review 重点

- 安全：认证、Origin/CSRF、密钥、错误响应和日志是否泄露信息。
- 数据：是否绕过 Gateway；缓存键、新鲜度、Provider trace 和 stale 降级是否完整。
- 语义：失败是否被误写成中性分；共识是否满足确定性/覆盖门槛。
- 持久化：迁移是否幂等、可备份、可恢复；业务库与缓存库是否分离。
- 策略：manifest、验证、批准和激活是否严格分离；结果能否追溯。
- 前端：是否只通过统一 API client；DOM 是否安全；真实 Chromium 是否零错误。
- 发布：是否绑定 exact commit/SHA256；candidate 和 rollback rehearsal 是否有证据。

## Git 与发布

提交应小而可审查，使用 `feat:`、`fix:`、`test:`、`docs:`、`ci:`、`ops:` 或 `chore:`。
PR 先合入 `verify`，远程 CI 全绿后才能使用
[安全部署流程](docs/ops/deploy-checklist.md)。不得在 VPS 创建临时提交、重置 checkout、
关闭 SSH 主机校验或在合并前操作生产。
