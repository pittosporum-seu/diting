# 谛听 · Issue 拆分

> 基于架构设计 v2.0 | 日期：2026-07-05
> 原则：一个 Issue = 一个可独立验证的交付物，依赖最小化
> 进度：M1 完成 ✅ | 22 tests · ruff ✅ · CLI ✅ | 下一步 M2 数据层

---

## M1: 骨架跑通（5 个 Issue）✅ 已完成

### #1 项目初始化 ✅
- [x] `pyproject.toml`：项目元数据 + 依赖声明（litellm, sandboxmcp, click, structlog, requests, openpyxl, vmdpy, PyWavelets, PyEMD, echarts）
- [x] `.gitignore`：排除 venv/__pycache__/.env/output/
- [x] `config/.env.example`：环境变量模板（不含真实值）
- [x] `LICENSE`：MIT
- [x] `README.md` ✅ 已有
- [x] `config/watchlist.example.csv`
**依赖：** 无 | **大小：** S

### #2 数据协议层 ✅
- [x] `src/diting/schema.py`：所有 @dataclass（RealtimeQuote, HistoricalData, VMDResult, TechnicalSignals, AnalysisContext, AnalysisResult, ConsensusScore, PipelineResult, PipelineMetrics）
- [x] `src/diting/enums.py`：Rating, DataSource, DataType, Signal
- [x] 单元测试：11 tests ✅
**依赖：** 无 | **大小：** M

### #3 基础设施层 ✅
- [x] `src/diting/infra/logging_config.py`：structlog 配置
- [x] `src/diting/infra/errors.py`：异常层次结构（DitingError, DataUnavailableError, EngineFailedError, SandboxError, PipelineError）
- [x] `src/diting/infra/decorators.py`：@cached, @retry, @log_latency
- [x] 单元测试：11 tests ✅
**依赖：** 无 | **大小：** M

### #4 CLI 入口 ✅
- [x] `src/diting/__init__.py`
- [x] `src/diting/config.py`：.env + watchlist.csv 解析
- [x] `src/diting/main.py`：click CLI（l0/l1/l2/run 命令已实现）
- [x] `diting --help` 可运行，显示 4 个子命令 ✅
**依赖：** #3 | **大小：** M

### #5 CI 流水线 ✅
- [x] `.github/workflows/ci.yml`：lint（ruff）+ 骨架测试（pytest）
- [x] `pyproject.toml` 中配置 ruff + pytest
- [x] ruff ✅ + pytest 22/22 ✅
**依赖：** #1-#4 | **大小：** S

---

## M2: 数据层（4 个 Issue）

### #6 DataProvider ABC ✅
- [x] `src/diting/data/providers/base.py`：DataProvider ABC
- [x] `health_check()`, `fetch_realtime()`, `fetch_historical()` 抽象方法
- [x] 单元测试：10 tests ✅
**依赖：** #2 | **大小：** S

### #7 MxDataProvider + AkShareProvider ✅
- [x] `src/diting/data/providers/mx_data.py`：东方财富 mx-data 实现
- [x] `src/diting/data/providers/akshare.py`：akshare 兜底实现
- [x] `src/diting/data/cache.py`：TTL 缓存层
- [x] 单元测试通过 ✓
**依赖：** #6 | **大小：** L

### #8 MarketDataRepository ✅
- [x] `src/diting/data/repository.py`：统一数据访问层
- [x] 降级链：mx-data → akshare → SQLite cache
- [x] 健康检查 + 自动降级 + 来源标注
- [x] 单元测试：11 tests ✅
**依赖：** #7 | **大小：** M

### #9 watchlist 解析 ✅
- [x] `config/watchlist.example.csv`：标准格式定义
- [x] Config 类支持加载 + 验证（代码格式/市场/必填列）
- [x] 去重 + validate=False 跳过
- [x] 单元测试：9 tests ✅
**依赖：** #4 | **大小：** S

---

## M3: 信号层（3 个 Issue）

### #10 技术指标计算 ✅
- [x] `src/diting/signals/technical.py`：RSI/MACD/KDJ/布林带/均线/VWAP/量比
- [x] 输入 HistoricalData → 输出 TechnicalSignals
- [x] 单元测试：10 tests ✅
**依赖：** #2 | **大小：** M

### #11 VMD 分解 ✅
- [x] `src/diting/signals/vmd.py`：VMD 分解（vmdpy, K=5, alpha=2000）
- [x] 周期位置/趋势斜率/主导周期 计算
- [x] 单元测试 + 异常处理
**依赖：** #2 | **大小：** M

### #12 小波去噪 + CEEMDAN ✅
- [x] `src/diting/signals/wavelet.py`：sym8 去噪
- [x] `src/diting/signals/ceemdan.py`：CEEMDAN 趋势提取（内联实现）
- [x] 单元测试：3 tests ✅
**依赖：** #2 | **大小：** S

---

## M4: 沙箱 + 第一个 AI 引擎（4 个 Issue）

### #13 AI 客户端（LiteLLM） ✅
- [x] `src/diting/ai/client.py`：统一 completion 接口
- [x] 配置驱动：model 字符串切换 provider
- [x] 错误处理：超时/限流/认证失败
- [x] 单元测试：4 tests ✅
**依赖：** #3 | **大小：** M

### #14 Python 沙箱（sandboxmcp） ✅
- [x] `src/diting/sandbox/executor.py`：sandboxmcp 封装
- [x] process 后端：内存 512MB / 时间 60s / import 白名单
- [x] 单元测试：1 test ✅
**依赖：** #3 | **大小：** L

### #15 引擎基类 + 注册机制 ✅
- [x] `src/diting/engines/base.py`：AnalysisEngine ABC
- [x] `src/diting/engines/registry.py`：@register_engine + discover_engines
- [x] 单元测试：3 tests ✅
**依赖：** #2 | **大小：** M

### #16 Wyckoff 引擎 ✅
- [x] `src/diting/engines/wyckoff.py`：威克夫 AI 分析引擎
- [x] System prompt 设计 + AI→沙箱→结果解析
- [x] 单元测试：6 tests ✅
**依赖：** #13, #14, #15 | **大小：** L

---

## M5: 全引擎 + 共识融合（4 个 Issue）

### #17 剩余引擎 ✅
- [x] `src/diting/engines/buffett.py`：巴菲特/芒格评分（AI + 沙箱）
- [x] `src/diting/engines/can_slim.py`：CANSLIM（AI + 沙箱）
- [x] `src/diting/engines/volume_profile.py`：Volume Profile（纯计算）
- [x] `src/diting/engines/vmd_rsi.py`：VMD+RSI 择时（纯计算）
- [x] 单元测试：5 tests ✅
**依赖：** #10, #11, #16 | **大小：** XL

### #18 分析管道 ✅
- [x] `src/diting/pipeline/runner.py`：AnalysisPipeline
- [x] 并行执行引擎 + 错误不阻塞
**依赖：** #17 | **大小：** L

### #19 评分融合 ✅
- [x] `src/diting/pipeline/consensus.py`：多引擎共识
- [x] 加权平均 + 冲突检测 + 置信度
- [x] 单元测试：3 tests ✅
**依赖：** #18 | **大小：** M

### #20 事件告警 ✅
- [x] `src/diting/pipeline/alert.py`：Observer 模式
- [x] RSI<20 / VMD 谷底 / 大盘暴跌 3% 三种告警
- [x] 单元测试：3 tests ✅
**依赖：** #10, #11 | **大小：** S

---

## M6: 报告 + 推送 + 发布（3 个 Issue）

### #21 报告生成 ✅
- [x] `src/diting/report/builder.py`：ReportBuilder（468行）
- [x] `src/diting/report/echarts.py`：ECharts 图表生成（364行）
- [x] 单页 HTML 模板：L1 简洁版 + L2 完整版，iPad 兼容 + 浅色主题
- [x] 单元测试：20 tests ✅
**依赖：** #19 | **大小：** L

### #22 推送渠道 ✅
- [x] `src/diting/notify/feishu.py`：飞书（桩实现）
- [x] `src/diting/notify/email.py`：邮件（桩实现）
- [x] `src/diting/notify/local.py`：本地保存
- [x] `src/diting/notify/base.py`：Notifier ABC
**依赖：** #21 | **大小：** M

### #23 发布准备 + 集成测试 ✅
- [x] QUICKSTART.md
- [x] pyproject.toml 完善（classifiers, keywords, version 0.1.0）
- [x] ECharts CDN 5.5.0 + viewport meta
- [x] 端到端集成测试：13 tests ✅
- [x] CLI smoke test：7 tests ✅
**依赖：** #22 | **大小：** M

---

## M7: 集成测试 + 发布 ✅ 完成

### #24 端到端集成测试 ✅
- [x] `tests/integration/test_pipeline_e2e.py`：13 tests
- [x] 完整管道测试：数据获取 → 信号 → 引擎 → 报告
- [x] mock 响应验证全链路
- [x] 错误降级测试
**依赖：** #21, #22 | **大小：** L

### #25 文档 + 发布 ✅
- [x] QUICKSTART.md
- [x] pyproject.toml（scripts, classifiers, keywords, version 0.1.0）
- [x] 版本号 0.1.0
**依赖：** #24 | **大小：** M

---

## Issue 统计

| Milestone | Issue 数 | S | M | L | XL |
|-----------|:------:|:-:|:-:|:-:|:-:|
| M1 骨架 | 5 ✅ | 2 | 3 | - | - |
| M2 数据 | 4 ✅ | 2 | 1 | 1 | - |
| M3 信号 | 3 ✅ | 1 | 2 | - | - |
| M4 沙箱+引擎 | 4 ✅ | - | 2 | 2 | - |
| M5 全引擎 | 4 ✅ | 1 | 1 | 1 | 1 |
| M6 报告+推送 | 3 ✅ | - | 1 | 1 | - |
| M7 集成+发布 | 2 ✅ | - | 1 | 1 | - |
| **合计** | **25 ✅** | **6** | **11** | **6** | **1** |

**🎉 全部完成：25/25 · 154 tests · ruff ✅ · version 0.1.0**

### 依赖图（关键路径）

```
#1 ──→ #2 ──→ #6 ──→ #7 ──→ #8
#1 ──→ #3 ──→ #13 ──→ #14
#2 ──→ #10 ──→ #11
#2, #3, #4 ──→ #15 ──→ #16 (M4 瓶颈)
#10, #11, #16 ──→ #17 ──→ #18 ──→ #19 ──→ #21 ──→ #22 ──→ #23
```

**可并行组：**
- M1：`#1 | #2, #3` 可并行
- M2：`#6 | #9` 可并行
- M3：`#10 | #11 | #12` 全部并行
- M4：`#13 | #14 | #15` 全部并行
- M5：`#17` 是瓶颈（XL），其余串行

---

*文档维护：小爪 | 谛听项目组 | 2026-07-06*
*状态：🎉 全部完成 · 25/25 issues · 154 tests · version 0.1.0 · MIT*
