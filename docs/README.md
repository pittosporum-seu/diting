# Diting documentation

文档按 Diátaxis 组织。若文档冲突，优先级为 `AGENTS.md`、Accepted v0.8 总体设计、运行时
OpenAPI/严格配置模型、其他活跃文档；历史设计仅用于理解演进。

## Tutorial

- [首次获取行情并完成分析](tutorials/quickstart.md)

## How-to

- [扩展 v0.8 分析引擎](how-to/extend-engine.md)
- [验证、批准和激活机会策略](how-to/activate-strategy.md)
- [部署、观察与回滚](ops/deploy-checklist.md)

## Reference

- [Python API、CLI 与 HTTP 契约](01-design/api-contracts.md)
- [严格配置参考](reference/configuration.md)
- [FastAPI 生成的 OpenAPI 3.1](api/diting-openapi.yaml)
- [领域数据模型](01-design/data-models.md)（迁移期参考；精确定义以 `schema.py` 为准）

## Explanation

- [v0.8.0 总体设计（Accepted）](01-design/v0.8.0-system-design.md)
- [设计文档状态索引](01-design/README.md)
- [研究治理与当前证据](research/INDEX.md)

## Project process

- [开发手册](../AGENTS.md)
- [贡献指南](../CONTRIBUTING.md)
- [当前任务计划](../tasks/plan.md)
- [任务状态](../tasks/todo.md)
