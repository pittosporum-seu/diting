# 谛听（Diting）

> A 股多模型投资研究与辅助判断工具。v0.8 以统一数据缓存、冻结分析快照、可追溯共识和
> 人工治理策略为核心；它提供证据，不替代投资决策。

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://python.org)

当前版本：`0.8.0`。这是破坏性版本：HTTP 只保留 `/api/v1/*`，CLI 已删除
`l0/l1/l2/run`，旧业务兼容层不会回退。

## 为什么是 v0.8

- Quote、历史行情、财务、资金流、证券目录和交易日历都经过统一 `DataGateway`；L1
  内存缓存与 `diting_cache.db` 共享同一新鲜度、来源追踪和降级语义。
- 每次分析先冻结数据、配置、策略和 deadline，再由一个 `AnalysisOrchestrator` 为 CLI、
  Python API、Web 和任务队列生成相同结果。
- 默认确定性引擎是 technical 与 volume profile；配置 AI 后可增加严格结构化输出的
  Wyckoff、CANSLIM 和 Buffett。非法/缺失 AI 输出是失败，不会变成 50 分。
- 共识必须有足够成功引擎、确定性证据和权重覆盖；证据不足时 `analysis_score` 为 `null`。
- 机会榜只读人工激活的策略。`mean_reversion_v1` 未经完整研究、批准和激活时，返回
  `NO_ACTIVE_STRATEGY`，不会使用历史 `dist_high_20` 权重。
- Web 匿名访问仅限显式公开读取；自选、分析/扫描创建、偏好和管理操作需要 Owner
  HttpOnly 会话、Origin 与 CSRF 校验。

## 快速开始

需要 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/pittosporum-seu/diting.git
cd diting
uv sync --extra dev

# 行情读取不隐式启动分析
uv run diting quote 002475

# standard；`uv run diting 002475` 是等价简写
uv run diting analyze 002475 --profile standard

# deep 会规划完整报告与 Buffett；是否有 AI 引擎取决于严格配置
uv run diting analyze 002475 --profile deep

# 未激活生产策略时明确失败，而不是回退旧榜单
uv run diting scan --limit 20
```

首次分析需要可用行情网络。没有 AI key 时，确定性引擎仍可运行；AI 引擎不会伪装成
成功。完整教程见[首次分析](docs/tutorials/quickstart.md)。

## Python API

```python
from diting import AnalysisProfile, Diting, FetchMode

with Diting.from_config() as client:
    quote = client.get_quote("002475", freshness=FetchMode.CACHE_PREFERRED)
    if quote.succeeded:
        print(quote.data.price, quote.cache_info.state, quote.provider_traces)

    run = client.analyze("002475", profile=AnalysisProfile.STANDARD)
    print(run.run_id, run.analysis_score, run.warnings)

    opportunities = client.scan(limit=20)
    print(opportunities.status, opportunities.error_code)
```

所有对象都有明确类型。使用 context manager 或调用 `close()` 释放 worker、缓存和数据源。

## Web 与 API

本地只读体验可显式开启：

```bash
DITING_PUBLIC_READONLY=true DITING_AI_ENABLED=false \
  uv run diting serve --host 127.0.0.1 --port 8100
```

打开 `http://127.0.0.1:8100/`。内部 API 是 `/api/v1/*`；生产 Caddy 前缀是
`/api/diting/v1/*`。精确请求/响应模型由 FastAPI 生成，见
[OpenAPI 3.1](docs/api/diting-openapi.yaml)。Owner 登录还需要安全配置，参见
[配置参考](docs/reference/configuration.md)。

## 架构概览

```text
CLI / HTTP / Python / jobs
            │
            ▼
application use cases ── AnalysisOrchestrator / ScanOrchestrator
            │
            ▼
domain dataclasses + ports
            ▲
            │
adapters ── CachedMarketDataGateway / SQLite / Providers / LLM / reports

bootstrap.py 是唯一组装根
```

业务状态写入 `diting.db`，可丢弃缓存写入 `diting_cache.db`。生产固定一个 uvicorn worker，
不依赖 Redis、消息队列、React 或 Vue。

## 质量门禁

```bash
uv run pre-commit run --all-files
uv run ruff check src/ tests/ browser_tests/ scripts/validate-api.py
uv run ruff format --check src/ tests/ browser_tests/ scripts/validate-api.py
uv run pytest tests/ -m "not network" -q
uv run python scripts/validate-api.py --check
uv run pytest browser_tests/ -q
```

CI 还检查全部前端 JavaScript、shell 脚本、锁文件和真实 Playwright Chromium 流程。测试
数量会增长，因此 README 不把某个历史数量当作质量声明。

## 文档

- [文档首页](docs/README.md)：按教程、How-to、参考和解释分类。
- [v0.8 总体设计](docs/01-design/v0.8.0-system-design.md)：Accepted 架构与决策。
- [API 契约](docs/01-design/api-contracts.md) 与 [OpenAPI](docs/api/diting-openapi.yaml)。
- [研究状态](docs/research/INDEX.md)：候选策略证据与生产状态。
- [安全部署](docs/ops/deploy-checklist.md)：candidate、演练、切换与回滚。
- [开发手册](AGENTS.md) 与 [贡献指南](CONTRIBUTING.md)。

## 限制与风险

- 这是研究工具，不构成投资建议；数据延迟、Provider 降级和模型误判都可能发生。
- 完整研究回测与外部网络测试不属于离线核心门禁；任何策略激活仍必须有真实、可复现的
  OOS 报告和 Owner 人工批准。
- 当前没有被项目伪造或默认激活的 `mean_reversion_v1`。机会榜不可用是正确状态。

MIT License。
