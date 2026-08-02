# AGENTS.md — 谛听 v0.8.0 施工手册

> 面向项目维护者与实现代理。开始任何工作前必须完整阅读本文和当前 Issue。

## 0. 项目与工作区

| 项目 | 约束 |
|---|---|
| 产品 | 谛听（Diting），A 股研究与辅助判断工具 |
| 目标版本 | v0.8.0 |
| 许可 | MIT |
| Python | 3.12+ |
| 包管理 | uv + `pyproject.toml` + `uv.lock` |
| 唯一代码源 | `C:\Users\13736\OneDrive\Documents\MyFiles\code\open-source\diting` |
| WSL 用途 | 只调用既有飞书通知脚本，不在 WSL 旧仓库实现代码 |
| 架构基线 | `docs/01-design/v0.8.0-system-design.md`（Accepted） |
| 执行计划 | `tasks/plan.md`、`tasks/todo.md` |

Windows 仓库是实现、测试、提交和发布包的唯一来源。WSL
`/home/pitto/workspace/diting` 是历史副本，除调用
`scripts/notify-diting.sh` 外不得从中复制代码、配置或凭据。

## 1. 不可违反的架构约束

### 1.1 模块化单体与依赖方向

```text
interfaces (CLI / HTTP / Python API / worker)
        -> application use cases
        -> core/domain + ports

adapters -> ports + domain
bootstrap -> interfaces + application + adapters  # 唯一组装根
```

- v0.8 不拆微服务，不引入 Redis、消息队列、多 worker、React 或 Vue。
- `application`、`engines`、`web`、`main.py` 不得构建具体 Provider、LLM、Sandbox、
  Cache 或 Repository；具体实现只允许在 adapters 与 `bootstrap.py` 组装。
- 下层不得 import 上层；用 AST 架构测试持续检查。
- Web 路由只负责认证、校验、映射和状态码，不计算指标、选择数据源或拼评分公式。

### 1.2 数据协议

- 核心跨模块业务对象使用 `@dataclass(frozen=True)`；共享协议集中在
  `src/diting/schema.py`，外部能力契约集中在 `src/diting/ports.py`。
- HTTP 边界允许 Pydantic 请求/响应模型，但必须映射为领域 dataclass 后再进入应用层。
- 禁止在 core/application 边界裸传业务 `dict` 或 `DataFrame`。DataFrame 只可存在于
  Provider 适配器和纯计算函数局部范围。
- 失败、部分成功、数据不足和有效中性必须是不同状态；禁止用 50 分表示解析、数据源、
  超时或共识失败。

### 1.3 唯一业务入口

- 数据获取统一通过 `CachedMarketDataGateway`，包括 Quote、Historical、Financials、
  FundFlow、Instrument Catalog 和 Trading Calendar。
- 分析统一通过 `DataSnapshotBuilder` + `AnalysisOrchestrator`。
- 扫描统一通过 `ScanOrchestrator`，且只能加载 active 策略。
- CLI、HTTP、Python API 和后台任务必须调用同一应用用例，不得各自复制流程。

### 1.4 数据缓存契约

- `diting.db` 保存业务状态；`diting_cache.db` 仅保存可丢弃的数据缓存与 Provider 健康状态。
- L1 是有界进程内缓存；L2 是 SQLite。v0.8 生产只运行一个 uvicorn worker。
- 支持 `CACHE_PREFERRED`、`FRESH_REQUIRED`、`CACHE_ONLY` 和 `force_refresh`。
- 每个 `DataResult[T]` 必须包含数据时间、缓存信息、Provider trace、warnings 和请求哈希。
- 同键 single-flight；连续 3 次失败熔断 60 秒；幂等瞬时错误最多重试 2 次并带抖动。
- 交易阶段来自交易所/Provider 日历，禁止用民用调休推断交易日。

### 1.5 分析与策略

- `standard`：technical、volume_profile、结构化 wyckoff；完整财务时加入 CANSLIM。
- `deep`：standard + Buffett + 完整报告；生成代码/沙箱研究能力必须显式开启。
- VMD 只作为上下文与证据，默认共识权重为 0。
- 共识至少需要 2 个成功引擎、1 个确定性引擎、50% 有效权重覆盖；否则
  `analysis_score=None`。
- 机会策略遵循 `draft → validated → approved → active → retired`。未激活时返回空榜与
  `NO_ACTIVE_STRATEGY`，绝不回退旧 `dist_high_20: 0.85` 权重。

### 1.6 API 与安全

- 内部 HTTP 路径为 `/api/v1/*`，Caddy 公网路径为 `/api/diting/v1/*`。
- 旧 API 统一返回 `410 API_VERSION_REMOVED`，不保留旧业务兼容层。
- 匿名只允许读取；自选、分析/扫描创建、任务、设置、缓存和策略操作要求 owner 会话。
- owner token 只以哈希形式校验；会话 Cookie 为 12 小时、HttpOnly、SameSite=Strict，
  生产必须 Secure；所有写请求检查 Origin 与 CSRF。
- 严禁把 token、session secret、API key、飞书凭据写入 Git、日志、报告或通知。

## 2. 实现与文档通信

当前 v0.8.0 由本工作区中的 Codex 直接完成设计、实现、测试、审查、提交、发布和通知，
不再强制委派给外部编码代理。不得以“由另一个代理完成”为理由跳过本文件的任何门禁。

每个实现任务仍必须使用仓库文档保持上下文：

```text
任务定义 -> docs/01-design/issues/v080-NN-*.md
执行状态 -> tasks/todo.md
Checkpoint 报告 -> docs/01-design/test-results/v080-checkpoint-*.md
完成通知 -> scripts/notify-diting.ps1 -> WSL notify-diting.sh -> 海桐
```

每个 Issue 必须写清设计引用、预计修改文件、验收标准和验证命令。普通任务应控制在约
3–5 个实现/测试文件；机械归一化、契约生成和跨入口迁移等不可分割任务必须在 Issue 中
明确说明例外，并单独审查 diff。

## 3. 配置与版本

- `pyproject.toml` 是版本唯一来源；CLI、FastAPI、Python API 与前端展示都读取包版本。
- 配置优先级固定为 CLI overrides > environment > YAML > defaults。
- 未知配置键必须报错；只有 bootstrap 读取原始配置。
- secrets、Provider base URL、生产策略选择不得被数据库偏好覆盖。
- 配置模板只包含占位符；禁止提交 `.env` 或真实值。

## 4. 开发与验证流程

### 4.1 每个任务

1. 完整阅读 Issue 和引用的设计章节。
2. 检查当前 diff，保留其他任务/用户修改。
3. 先写或更新聚焦测试，再实现最小纵向切片。
4. 执行 Issue 中的聚焦测试与 lint。
5. 写完成报告，包含改动文件、命令原文、结果、未解决风险。
6. 更新 `tasks/todo.md`，并在 Checkpoint 写验证报告；不得写伪造提交号或测试结果。
7. 用通知包装器向海桐报告 Checkpoint，不包含任何密钥。

### 4.2 Checkpoint 与推送前门禁

```powershell
uv sync --extra dev
uv run pre-commit run --all-files
uv run ruff check src/ tests/ browser_tests/ scripts/validate-api.py
uv run ruff format --check src/ tests/ browser_tests/ scripts/validate-api.py
uv run pytest tests/ -m "not network" -q
uv run python scripts/validate-api.py --check
uv run pytest browser_tests/ -q
```

还必须执行：

- 对全部 `frontend/**/*.js` 运行 `node --check`。
- 运行 API/OpenAPI、严格配置和 AST 依赖检查。
- Playwright fixture 启动本地 uvicorn，以真实 Chromium 验证五个页面及关键交互。
- 浏览器不得有 console error、page error、未处理 promise 或失败资源。
- 网络测试和完整研究回测单独运行；网络偶发失败不阻塞核心测试，但策略激活必须依赖
  完整、可复现的研究报告。

禁止使用 `--no-verify`、跳过测试的部署参数或用“测试数量”代替完成定义。

## 5. 代码规范

- 使用 `structlog`，禁止业务代码 `print`；生产错误响应不返回堆栈。
- 所有新文件含模块 docstring；使用 `uv run`，不用裸 `python`。
- 所有外部调用设置 deadline/timeout；宽泛异常捕获必须记录结构化原因并映射为明确状态。
- 引擎通过显式 registry 构建，禁止 import 副作用发现。
- LLM 默认只返回严格结构化数据；非法 JSON、缺字段和越界值均为 EngineRun failure。
- 配置、策略、prompt、engine 与数据快照均需版本/哈希，保证可追溯与可复现。

## 6. 数据源避坑

- 个股与 ETF 分开查询；mx-data 每批最多 4 只；ETF 使用代码而非简称。
- ETF 复权单位净值不等于涨跌幅；用规范化收盘价计算。
- mx-data 历史查询必须给明确日期范围，价格字符串清理单位后再转换。
- VMD 参数顺序为 `VMD(signal, alpha, tau, K, DC, init, tol)`，输入至少 `K * 10` 天；
  输出长度差异和内存释放必须测试。
- Provider 返回值先在 adapter 内规范化，再进入 Gateway；不得把第三方 DataFrame 泄漏到核心。

## 7. 研究治理

研究任务开始前先读 `docs/research/INDEX.md`。研究数据也必须通过 Data Gateway 获取，
manifest 至少记录 Provider trace、复权、证券存续区间、数据版本与快照哈希。

硬性方法：

1. ground truth 只用真实未来收益，不用 AI 分。
2. 因子方向和权重只在训练集确定。
3. 先单因子，再去冗余，再组合；绝对相关性大于 0.7 只保留训练 IC_IR 更高者。
4. 使用固定 train/validation/OOS 窗口、point-in-time 股票池与交易成本。
5. 达到统计门槛只进入 validated；approved/active 必须由 owner 显式操作。
6. VMD 当前证据不足以进入生产排名，只可作为 AI 上下文。

原始 CSV、PKL、日志和数据缓存不入 Git。Git 中仅保存 manifest、精简 JSON、研究说明和
可复现实验代码；大文件位于外部归档或 `experiment/` ignored 路径。

## 8. 文档体系

采用 Diátaxis：

| 类型 | 文档 |
|---|---|
| Explanation | `docs/01-design/v0.8.0-system-design.md` |
| Reference | OpenAPI、API/配置/Schema 参考 |
| How-to | 部署、扩展引擎、发布策略、故障处理 |
| Tutorial | README/Quickstart 的首次分析流程 |

历史设计保留但必须标记 superseded。代码、配置、OpenAPI 或部署行为改变时，同一任务中
更新相应参考/How-to，不能修改设计来迁就缺陷。

## 9. Git、发布与通知

- 工作分支使用 `codex/` 前缀；v0.8 分支为 `codex/v0.8.0`。
- 提交必须小而可审查，Checkpoint 全绿后才提交；不得改写或丢弃用户已有改动。
- PR 合并 `verify` 前不操作生产。发布包绑定确定 commit 与 SHA256。
- VPS 使用非 root 用户、Python 3.12、隔离 release 目录、candidate 8101、数据库副本迁移、
  Caddy 原子切换和可演练回滚；禁止 `StrictHostKeyChecking=no` 和 VPS 临时提交。

通知命令（Task 00 完成后）：

```powershell
./scripts/notify-diting.ps1 -Title "✅ Checkpoint C1" -Body "commit: ...`ntests: ...`nrisks: ..."
```

包装器只把标题和正文传给 WSL 既有脚本；不读取、不显示、不复制脚本内凭据。

## 10. 完成定义

一个任务只有在实现、聚焦测试、lint、报告、状态记录和通知均完成后才可勾选。v0.8.0
只有在核心/契约/安全/浏览器/迁移/策略治理/部署回滚全部验证后才算完成；如果
`mean_reversion_v1` 未通过门槛，版本仍可发布，但机会榜必须明确不可用。

---

*文档维护：谛听项目组 | v0.8.0 Accepted | 2026-08-02*
