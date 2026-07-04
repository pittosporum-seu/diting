# 谛听 · 企业级开发流程

> 版本：v1.0 | 日期：2026-07-04

---

## 阶段总览

```
设计阶段 (1-2周)
  ├── 需求分析
  ├── 功能设计
  ├── 架构设计
  ├── 数据模型设计
  ├── API 契约设计
  └── 设计评审 ← 全团队参加

规划阶段 (2-3天)
  ├── Issue 拆分
  ├── Milestone 规划
  └── Sprint 排期

开发阶段 (迭代)
  ├── Sprint 1: 核心骨架
  ├── Sprint 2: 数据层
  ├── Sprint 3: 信号层
  ├── Sprint 4: 分析引擎
  ├── Sprint 5: 报告+推送
  └── Sprint 6: CI/CD + 文档

发布阶段
  ├── 内部测试
  ├── Beta 发布
  └── 正式发布 (v1.0.0)
```

---

## 设计阶段 Checklist

- [ ] 功能设计文档：做什么、不做什么
- [ ] 调研文档：有哪些现成的可以参考/复用
- [ ] 架构设计：分层、设计模式、依赖方向
- [ ] 数据模型：所有 @dataclass、枚举、协议
- [ ] API 契约：CLI 命令、Python API、配置文件
- [ ] 设计评审：找问题、迭代、定稿

**铁律：设计不定稿，不写代码。** 设计阶段的改动成本低，代码阶段的改动成本高 10 倍。

---

## Issue 拆分原则

1. **一个 Issue = 一个可独立交付的模块**
2. **依赖最小化**：Issue A 不阻塞 Issue B
3. **可验证**：每个 Issue 有明确的完成标准（用 `[ ]` 列表）

### 示例 Issue

```markdown
## Issue: 实现 DataProvider ABC + MxDataProvider

### 完成标准
- [ ] `src/diting/data/providers/base.py`: DataProvider ABC
- [ ] `src/diting/data/providers/mx_data.py`: MxDataProvider
- [ ] 单元测试：mock mx-data 响应
- [ ] 健康检查可运行

### 依赖
- 无（Layer 1，不依赖上层）
```

---

## 目录 agent.md 规范

每个重要目录放一个 `agent.md`：

```
src/diting/data/agent.md:
  此目录是 Layer 1 数据访问层。
  规则：
  - 只依赖 infra 层，不依赖 signals/engines/pipeline/report/notify
  - 所有 Provider 实现 DataProvider ABC
  - 新增数据源：继承 ABC + 放 providers/ 子目录
  - 降级链在 repository.py 中配置
```

---

## Git 工作流

```
main ← 受保护，CI 通过才能 merge
  ├── feature/xxx ← 从 main 分出
  ├── fix/xxx
  └── docs/xxx

PR 规范：
- 标题：[模块] 简要描述
- 关联 Issue：#NN
- Checklist：测试通过 / 文档更新 / 无 lint 错误
```

---

## 测试策略

| 层级 | 测试类型 | 覆盖目标 |
|------|---------|---------|
| L0 (infra) | 单元测试 | >90% |
| L1 (data) | 单元 + 集成（mock API） | >80% |
| L2 (signals) | 单元（固定输入→固定输出） | >80% |
| L3 (engines) | 集成（AI mock + 沙箱真实执行） | >60% |
| L4 (pipeline) | 集成（端到端） | >50% |
| L5 (cli/report) | E2E（smoke test） | 关键路径 |

---

*文档维护：小爪 | 谛听项目组 | 2026-07-04*
