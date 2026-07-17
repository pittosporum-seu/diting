# 谛听 v0.1.0 开发治理规范

> 作用：确保所有代码变更遵循设计文档。  
> 对象：小爪（设计）+ CodeWhale（实现）。  
> 原则：设计先行，验证后行，不跳过任何一步。

---

## 一、开发流程（铁律）

```
1. 小爪出设计  ──→  2. 创建 Issue  ──→  3. CodeWhale 实现  ──→  4. 小爪审核  ──→  5. 合入
    │                   │                    │                      │
    └─ 设计文档         └─ Issue 模板       └─ 遵循本规范         └─ 检查清单
```

**任何一步未通过，不得进入下一步。**

---

## 二、Issue 模板

每个 Issue 必须包含以下字段，缺一不可：

```markdown
---
type: feature | bugfix | refactor
design_ref: docs/01-design/v0.1.0-xxx.md  # 对应设计文档
测试用例: [ ] 列出所有需通过的测试
依赖: [ ] 列出前置 Issue 编号
---

## 目标
一句话描述要做什么。

## 设计要点
- 数据从哪里来，到哪里去
- 数据格式是什么（引用 schema）
- 错误如何处理（引用错误码）
- 新鲜度如何传递

## 实现文件
- 新建: src/diting/xxx.py
- 修改: src/diting/yyy.py (第N行附近)
- 测试: tests/unit/test_xxx.py

## 验收标准
- [ ] pytest 全绿
- [ ] ruff check 通过
- [ ] 所有测试用例手动验证通过
- [ ] 新鲜度字段在所有响应中非空
- [ ] 错误响应符合契约格式
```

---

## 三、分支策略

```
main ───────────────────────────── (稳定，可部署)
  │
  └── verify ──────────────────── (集成测试分支)
        │
        ├── feat/freshness-proto  (Step 1: 基础设施)
        ├── feat/dashboard-fresh   (Step 2: 仪表盘)
        ├── feat/stock-pipeline    (Step 3: 个股)
        ├── feat/watchlist-api     (Step 4: 自选股)
        └── feat/scan-settings     (Step 5: 选股+设置)
```

**规则：**
- `main` 只接受来自 `verify` 的 merge
- `verify` 只接受通过全部测试的 PR
- 每个功能分支开发完成后合并到 `verify`
- 禁止直接 push 到 `main` 或 `verify`

---

## 四、提交规范

```
type(scope): 简短描述

- 详细说明（如有）
- 关联 Issue: #N
```

**type：** `feat` | `fix` | `refactor` | `test` | `docs` | `chore`

**示例：**
```
feat(schema): add FreshnessInfo dataclass

- 新增 src/diting/schema.py FreshnessInfo
- 所有 API 响应增加 freshness 字段
- 关联 Issue: #1
```

---

## 五、代码审查检查清单

每个 PR 合并前，小爪必须确认以下所有项：

### 架构层面
- [ ] 下层不 import 上层（参考 AGENTS.md §1.1）
- [ ] 跨模块数据用 `@dataclass`，禁裸传 dict
- [ ] Provider 不直接暴露给 Service（通过 Repository）

### API 契约
- [ ] 所有响应使用 `_api_response()` 信封
- [ ] `freshness` 字段在需要时非空
- [ ] 错误使用 `ErrorCode` 枚举，不裸传字符串
- [ ] 所有端点有对应的测试用例

### 数据流
- [ ] 从 provider 到 response，freshness 逐层显式传递
- [ ] 缓存读写不吞异常（记录日志后向上抛或返回 None）
- [ ] DB 操作用命名列索引（`row['key']`），不用位置索引

### 测试
- [ ] 新代码有对应的单元测试
- [ ] 修改的端点有更新测试
- [ ] `ruff check` 零问题
- [ ] `pytest` 新增 case 通过

---

## 六、质量门禁

### 开发阶段门禁

```
Step N 开始前:
  ✅ 上一步所有测试通过
  ✅ 设计文档已锁定（不再修改）

Step N 进行中:
  ✅ 每个端点实现后立即跑对应测试
  ✅ 不让 bug 跨 commit

Step N 完成后:
  ✅ 全部测试通过 (pytest + ruff)
  ✅ 手动 E2E 验证 (curl 所有新/改端点)
  ✅ 记录测试结果到 docs/01-design/test-results/
```

### 合入门禁

```
PR → verify 分支:
  1. pytest --cov 覆盖率 >= 新增代码的 60%
  2. ruff check zero
  3. 小爪逐条过审查检查清单
  4. 小爪手动 curl 验证所有改动的端点

verify → main:
  1. Playwright E2E 全绿（Phase 4 起）
  2. deploy.sh --skip-tests 成功部署到 VPS
  3. 生产环境手动抽检 3 个端点
```

---

## 七、测试结果记录模板

每个 Step 完成后，生成测试报告：

```markdown
# Step N 测试报告

日期: YYYY-MM-DD
执行人: 小爪

## 单元测试
- pytest: X passed, Y failed
- 新增: Z 个测试用例
- 覆盖率: XX%

## API 契约验证
| 端点 | 状态 | 新鲜度 | 备注 |
|------|:---:|:---:|------|
| GET /health | ✅ | N/A | |
| GET /dashboard | ✅ | ✅ | age_seconds=30 |
| GET /stock/000001 | ✅ | ✅ | 含 chart_data |
| GET /stock/999999 | ✅ (404) | N/A | 正确错误码 |

## 部署验证
- VPS 部署: ✅
- 浏览器仪表盘: ✅ / ⚠️ / ❌
- 浏览器个股分析: ✅ / ⚠️ / ❌
```

---

## 八、文件结构（开发完成后）

```
diting/
├── docs/01-design/
│   ├── v0.1.0-backend-design.md      # 后端设计（本文档）
│   ├── v0.1.0-architecture-redesign.md # 架构重构决策
│   ├── v0.1.0-data-flow-spec.md       # 数据流规范
│   └── test-results/                  # 测试报告
│       ├── step1-infra.md
│       ├── step2-dashboard.md
│       └── ...
├── AGENTS.md                          # CodeWhale 施工规范
└── CONTRIBUTING.md                    # 本文档（开发治理规范）
```

---

## 九、开始开发前的最终确认

在开始 Step 1 之前，确认以下所有项：

- [x] 设计文档完成（3 份）
- [x] 版本号回退到 0.1.0
- [x] API 契约全部定义（13 个端点）
- [x] 测试用例全部列出（每个端点 4-8 条）
- [x] 数据架构定义（FreshnessInfo + ErrorCode）
- [x] 开发流程定义（Issue → CodeWhale → 审查 → 合入）
- [x] 分支策略定义
- [x] 代码审查检查清单定义
- [x] `前端 API_BASE` 对齐（本地 `/api/` vs VPS `/api/diting/`）
- [x] `test-results/` 目录创建
- [ ] CodeWhale 接入准备（GitHub token, CodeWhale 配置）
