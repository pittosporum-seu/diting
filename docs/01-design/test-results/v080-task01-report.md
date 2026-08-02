# v0.8.0 Task 01 完成报告

## 结论

版本与严格配置基础已完成。

- `pyproject.toml` 的项目版本已设为 `0.8.0`，`uv.lock`、包元数据、CLI 和 FastAPI 均从该来源取得版本。
- 配置模型基于冻结 Pydantic v2 模型，未知字段拒绝，优先级固定为 defaults < YAML < environment < explicit overrides。
- 密钥字段禁止写入 YAML，只允许从环境变量或显式运行时注入；`SecretStr` 防止明文进入 repr。
- `ConfigLoader` 不再读取文件或环境，只暴露 bootstrap 已验证的不可变快照。
- 旧 `Config` 仅保留 watchlist CSV→SQLite 迁移和少量兼容读接口，不再加载 `.env` 或修改 `os.environ`。

## 验证

- `uv run pytest tests/unit/test_app_config.py tests/unit/test_config.py tests/unit/test_version.py -q`：20 passed。
- 版本一致性覆盖包、CLI、FastAPI 和 `pyproject.toml`。
- 配置测试覆盖未知字段、嵌套拼写错误、优先级、冻结状态、密钥来源和缺失配置文件。

## 风险

旧模块仍通过 `ConfigLoader.get_section()` 读取验证后的 dict 视图；后续纵向迁移时改为构造参数注入，并最终删除兼容接口。
