# 谛听 · 路线图

> 版本：v1.0 | 日期：2026-07-04

---

## 🎯 当前阶段：M2 数据层

- [x] ~~架构设计文档 v2.0 评审通过~~ ✅
- [x] ~~所有设计文档补全 + 评审~~ ✅
- [x] ~~Issue 拆分 + Milestone 规划~~ ✅

## 🏗️ Sprint 1: 项目骨架 ✅ 已完成

- [x] pyproject.toml + 依赖声明
- [x] 目录结构创建
- [x] schema.py（所有 @dataclass）
- [x] enums.py
- [x] config.py
- [x] infra/ 基础设施（logging, errors, decorators）
- [x] CLI 入口（diting --help 可运行）
- [x] CI pipeline（lint + test）→ ruff ✅ + pytest 22/22 ✅

## 📊 Sprint 2: 数据层

- [ ] DataProvider ABC
- [ ] MxDataProvider（东方财富）
- [ ] AkShareProvider（免费兜底）
- [ ] CacheLayer（TTL）
- [ ] MarketDataRepository（降级链）
- [ ] SQLite 本地缓存
- [ ] 健康检查 + 重试

## 📈 Sprint 3: 信号处理层

- [ ] 技术指标计算（RSI/MACD/KDJ/布林/均线）
- [ ] VMD 分解（vmdpy）
- [ ] 小波去噪（PyWavelets）
- [ ] CEEMDAN（PyEMD）
- [ ] 信号结果 @dataclass

## 🧠 Sprint 4: 分析引擎层

- [ ] AnalysisEngine ABC + registry
- [ ] sandboxmcp 集成（process 后端，seccomp + namespace）
- [ ] LiteLLM 集成（统一 100+ provider completion 接口）
- [ ] AI 代码生成 → 沙箱执行 → traceback 自动修复循环
- [ ] Wyckoff 引擎（LiteLLM → 沙箱 → 审计日志）
- [ ] Buffett/Munger 评分引擎（LiteLLM + 沙箱）
- [ ] CANSLIM 引擎（LiteLLM + 沙箱）
- [ ] Volume Profile 引擎（纯计算）
- [ ] VMD+RSI 择时引擎（纯计算）
- [ ] 多引擎共识融合

## 📝 Sprint 5: 报告 + 推送

- [ ] HTML 报告模板 + ECharts
- [ ] ReportBuilder
- [ ] PDF 导出（Chrome headless）
- [ ] FeishuNotifier（消息 + 文档 + Bitable）
- [ ] EmailNotifier
- [ ] LocalSaver
- [ ] 事件告警（Observer 模式）

## 🚀 Sprint 6: 发布准备

- [ ] 完整测试覆盖
- [ ] README + QUICKSTART
- [ ] API 文档
- [ ] .github/workflows CI/CD
- [ ] PyPI 发布脚本
- [ ] v1.0.0 release

## 📋 待办池（Backlog）

- [ ] 更多分析引擎（DCF, 谐波形态, 一目均衡表）
- [ ] Web UI（FastAPI + 前端）
- [ ] 实时行情推送（WebSocket）
- [ ] 多市场支持（港股/美股）
- [ ] 策略回测框架
- [ ] 社区插件市场

---

*文档维护：小爪 | 谛听项目组 | 2026-07-04*
