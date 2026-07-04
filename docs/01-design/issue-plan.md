# 谛听 · Issue 拆分

> 基于架构设计 v2.0 | 日期：2026-07-04
> 原则：一个 Issue = 一个可独立验证的交付物，依赖最小化

---

## M1: 骨架跑通（5 个 Issue）

### #1 项目初始化
- [ ] `pyproject.toml`：项目元数据 + 依赖声明（litellm, sandboxmcp, click, structlog, requests, openpyxl, vmdpy, PyWavelets, PyEMD, echarts）
- [ ] `.gitignore`：排除 venv/__pycache__/.env/output/
- [ ] `config/.env.example`：环境变量模板（不含真实值）
- [ ] `LICENSE`：MIT
- [ ] `README.md` ✅ 已有
**依赖：** 无 | **大小：** S

### #2 数据协议层
- [ ] `src/diting/schema.py`：所有 @dataclass（RealtimeQuote, HistoricalData, VMDResult, TechnicalSignals, AnalysisContext, AnalysisResult, ConsensusScore, PipelineResult, PipelineMetrics）
- [ ] `src/diting/enums.py`：Rating, DataSource, DataType, Signal
- [ ] 单元测试：dataclass 序列化/反序列化
**依赖：** 无 | **大小：** M

### #3 基础设施层
- [ ] `src/diting/infra/logging_config.py`：structlog 配置
- [ ] `src/diting/infra/errors.py`：异常层次结构（DitingError, DataUnavailableError, EngineFailedError, SandboxError, PipelineError）
- [ ] `src/diting/infra/decorators.py`：@cached, @retry, @log_latency
- [ ] 单元测试
**依赖：** 无 | **大小：** M

### #4 CLI 入口
- [ ] `src/diting/__init__.py`
- [ ] `src/diting/config.py`：.env + watchlist.csv 解析
- [ ] `src/diting/main.py`：click CLI（l0/l1/l2/run 命令占位，print 提示）
- [ ] `diting --help` 可运行，显示 4 个子命令
**依赖：** #3 | **大小：** M

### #5 CI 流水线
- [ ] `.github/workflows/ci.yml`：lint（ruff）+ 骨架测试（pytest）
- [ ] `pyproject.toml` 中配置 ruff + pytest
- [ ] CI 绿灯
**依赖：** #1-#4 | **大小：** S

---

## M2: 数据层（4 个 Issue）

### #6 DataProvider ABC
- [ ] `src/diting/data/providers/base.py`：DataProvider ABC
- [ ] `health_check()`, `fetch_realtime()`, `fetch_historical()` 抽象方法
- [ ] 单元测试：mock provider
**依赖：** #2 | **大小：** S

### #7 MxDataProvider + AkShareProvider
- [ ] `src/diting/data/providers/mx_data.py`：东方财富 mx-data 实现
- [ ] `src/diting/data/providers/akshare.py`：akshare 兜底实现
- [ ] `src/diting/data/cache.py`：TTL 缓存层
- [ ] 集成测试：mock API 响应，验证降级链
**依赖：** #6 | **大小：** L

### #8 MarketDataRepository
- [ ] `src/diting/data/repository.py`：统一数据访问层
- [ ] 降级链：mx-data → akshare → SQLite cache
- [ ] 健康检查 + 自动降级 + 来源标注
- [ ] 集成测试
**依赖：** #7 | **大小：** M

### #9 watchlist 解析
- [ ] `config/watchlist.example.csv`：标准格式定义
- [ ] Config 类支持加载 watchlist
- [ ] 验证：代码格式 / 必填字段
**依赖：** #4 | **大小：** S

---

## M3: 信号层（3 个 Issue）

### #10 技术指标计算
- [ ] `src/diting/signals/technical.py`：RSI/MACD/KDJ/布林带/均线/VWAP/量比
- [ ] 输入 HistoricalData → 输出 TechnicalSignals
- [ ] 单元测试：固定输入→固定输出
**依赖：** #2 | **大小：** M

### #11 VMD 分解
- [ ] `src/diting/signals/vmd.py`：VMD 分解（vmdpy, K=6, alpha=2000）
- [ ] 周期位置/趋势斜率/主导周期 计算
- [ ] 缓存策略：收盘后预计算，存入 SQLite
- [ ] 单元测试 + 异常处理（数据不足 50 天）
**依赖：** #2 | **大小：** M

### #12 小波去噪 + CEEMDAN
- [ ] `src/diting/signals/wavelet.py`：sym8 去噪
- [ ] `src/diting/signals/ceemdan.py`：CEEMDAN 趋势提取
- [ ] 单元测试
**依赖：** #2 | **大小：** S

---

## M4: 沙箱 + 第一个 AI 引擎（4 个 Issue）

### #13 AI 客户端（LiteLLM）
- [ ] `src/diting/ai/client.py`：统一 completion 接口
- [ ] 配置驱动：model 字符串切换 provider
- [ ] 错误处理：超时/限流/认证失败
- [ ] 集成测试：mock LiteLLM
**依赖：** #3 | **大小：** M

### #14 Python 沙箱（sandboxmcp）
- [ ] `src/diting/sandbox/executor.py`：sandboxmcp 封装
- [ ] process 后端：内存 512MB / 时间 60s / import 白名单
- [ ] AI 代码执行 → traceback 返回 → AI 重试 1 次
- [ ] 审计日志：每次执行记录 compute_log
- [ ] 集成测试
**依赖：** #3 | **大小：** L

### #15 引擎基类 + 注册机制
- [ ] `src/diting/engines/base.py`：AnalysisEngine ABC
- [ ] `src/diting/engines/registry.py`：@register_engine + discover_engines
- [ ] 引擎发现：自动扫描 engines/ 目录
- [ ] 单元测试
**依赖：** #2 | **大小：** M

### #16 Wyckoff 引擎
- [ ] `src/diting/engines/wyckoff.py`：威克夫 AI 分析引擎
- [ ] System prompt 设计：Phase A-E 识别 + Spring/SOS 信号
- [ ] AI 生成计算代码 → 沙箱执行 → 结果解析
- [ ] 输出：Wyckoff 阶段 + 信号列表 + 置信度 + compute_log
- [ ] 集成测试：mock AI 响应 + 真实沙箱
**依赖：** #13, #14, #15 | **大小：** L

---

## M5: 全引擎 + 共识融合（4 个 Issue）

### #17 剩余引擎
- [ ] `src/diting/engines/buffett.py`：巴菲特/芒格评分（AI + 沙箱）
- [ ] `src/diting/engines/can_slim.py`：CANSLIM（AI + 沙箱）
- [ ] `src/diting/engines/volume_profile.py`：Volume Profile（纯计算）
- [ ] `src/diting/engines/vmd_rsi.py`：VMD+RSI 择时（纯计算）
- [ ] 每个引擎的 system prompt + 沙箱代码模板
**依赖：** #10, #11, #16 | **大小：** XL

### #18 分析管道
- [ ] `src/diting/pipeline/runner.py`：AnalysisPipeline
- [ ] `src/diting/pipeline/pipeline.yaml`：管道配置
- [ ] 并行执行引擎 + 错误不阻塞
- [ ] 管道指标收集
**依赖：** #17 | **大小：** L

### #19 评分融合
- [ ] `src/diting/pipeline/consensus.py`：多引擎共识
- [ ] 加权平均 + 冲突检测 + 置信度
- [ ] 单引擎降级策略
**依赖：** #18 | **大小：** M

### #20 事件告警
- [ ] Observer 模式：信号触发→推送
- [ ] RSI<20 / VMD 谷底 / 大盘暴跌 3% 三种告警
- [ ] 阈值可配置
**依赖：** #10, #11 | **大小：** S

---

## M6: 报告 + 推送 + 发布（3 个 Issue）

### #21 报告生成
- [ ] `src/diting/report/builder.py`：ReportBuilder
- [ ] `src/diting/report/echarts.py`：ECharts 图表生成
- [ ] 单页 HTML 模板：iPad 兼容 + 浅色主题
- [ ] PDF 导出（Chrome headless）
**依赖：** #19 | **大小：** L

### #22 推送渠道
- [ ] `src/diting/notify/feishu.py`：飞书（消息 + 文档 + Bitable）
- [ ] `src/diting/notify/email.py`：邮件（HTML 内嵌）
- [ ] `src/diting/notify/local.py`：本地保存
- [ ] Notifier ABC
**依赖：** #21 | **大小：** M

### #23 发布准备
- [ ] QUICKSTART.md
- [ ] PyPI 发布脚本
- [ ] 版本号管理
- [ ] 完整端到端测试（smoke test）
**依赖：** #22 | **大小：** S

---

## Issue 统计

| Milestone | Issue 数 | S | M | L | XL |
|-----------|:------:|:-:|:-:|:-:|:-:|
| M1 骨架 | 5 | 2 | 3 | - | - |
| M2 数据 | 4 | 2 | 1 | 1 | - |
| M3 信号 | 3 | 1 | 2 | - | - |
| M4 沙箱+引擎 | 4 | - | 2 | 2 | - |
| M5 全引擎 | 4 | 1 | 1 | 1 | 1 |
| M6 发布 | 3 | 1 | 1 | 1 | - |
| **合计** | **23** | **7** | **10** | **5** | **1** |

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

*文档维护：小爪 | 谛听项目组 | 2026-07-04*
