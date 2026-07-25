# 谛听 · 路线图

> 版本：v2.0 | 日期：2026-07-25

---

## 当前阶段：发布准备

- [x] 架构设计文档 v2.0 评审通过
- [x] 所有设计文档补全 + 评审
- [x] Issue 拆分 + Milestone 规划
- [x] 仓库规范化（Issue/PR 模板、CI 编排、依赖锁定、安全策略）

## Sprint 1: 项目骨架 — 已完成

- [x] pyproject.toml + 依赖声明
- [x] 目录结构创建
- [x] schema.py（所有 @dataclass）
- [x] enums.py
- [x] config.py
- [x] infra/ 基础设施（logging, errors, decorators）
- [x] CLI 入口（diting --help 可运行）
- [x] CI pipeline（lint + test）

## Sprint 2: 数据层 — 已完成

- [x] DataProvider ABC
- [x] MxDataProvider（东方财富）
- [x] AkShareProvider（免费兜底）
- [x] CacheLayer（TTL）
- [x] MarketDataRepository（降级链）
- [x] SQLite 本地缓存
- [x] 健康检查 + 重试

## Sprint 3: 信号处理层 — 已完成

- [x] 技术指标计算（RSI/MACD/KDJ/布林/均线）
- [x] VMD 分解（vmdpy）
- [x] 小波去噪（PyWavelets）
- [x] CEEMDAN（PyEMD）
- [x] 信号结果 @dataclass

## Sprint 4: 分析引擎层 — 已完成

- [x] AnalysisEngine ABC + registry
- [x] sandboxmcp 集成（process 后端）
- [x] LiteLLM 集成（统一 100+ provider completion 接口）
- [x] AI 代码生成 → 沙箱执行 → traceback 自动修复循环
- [x] Wyckoff 引擎（LiteLLM → 沙箱 → 审计日志）
- [x] Buffett/Munger 评分引擎（LiteLLM + 沙箱）
- [x] CANSLIM 引擎（LiteLLM + 沙箱）
- [x] Volume Profile 引擎（纯计算）
- [x] VMD+RSI 择时引擎（纯计算）
- [x] 多引擎共识融合（Verdict 引擎）

## Sprint 5: 报告 + 推送 — 已完成

- [x] HTML 报告模板 + ECharts
- [x] ReportBuilder
- [x] FeishuNotifier（消息推送）
- [x] EmailNotifier
- [x] LocalSaver
- [x] 事件告警（Observer 模式）

## Sprint 6: Web UI — 已完成

- [x] FastAPI 后端（/api/diting 路由）
- [x] 前端 SPA（原生 JS + ECharts）
- [x] 自选股管理
- [x] 实时行情面板
- [x] 分析报告在线查看

## Sprint 7: 发布准备 — 进行中

- [x] 完整测试覆盖（unit / integration / e2e 三层）
- [x] README + QUICKSTART
- [x] API 文档（OpenAPI spec）
- [x] CI/CD 流水线（中心编排 + 子 workflow）
- [x] GitHub 模板体系（Issue / PR / Dependabot）
- [x] 依赖精确版本锁定
- [x] 安全策略（SECURITY.md）
- [ ] PyPI 发布脚本
- [ ] v1.0.0 release

## 待办池（Backlog）

- [ ] 更多分析引擎（DCF, 谐波形态, 一目均衡表）
- [ ] 实时行情推送（WebSocket）
- [ ] 多市场支持（港股/美股）
- [ ] 策略回测框架
- [ ] 社区插件市场
- [ ] PDF 导出（Chrome headless）

---

*文档维护：谛听项目组 | 2026-07-25*
