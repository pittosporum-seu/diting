# v0.8.0 Task 03 完成报告

## 结论

唯一 bootstrap 组合根已建立。

- `ApplicationContainer` 和 `ApplicationDependencies` 均为冻结 dataclass，可完整注入 fake adapters。
- `bootstrap_application()` 是原始 YAML/环境读取与 ConfigLoader 注册的唯一调用边界。
- CLI Provider 链和 MX 连通性 Repository 构造已从 `main.py` 移入 bootstrap。
- FastAPI 初始化通过 bootstrap 验证配置，不再用 `Config()` 隐式加载 `.env`。
- AST 门禁禁止新增具体行情 Provider import 绕过。

## 验证

- bootstrap/AST/schema/ports 聚焦测试：28 passed。
- fake container 构造不访问网络、不创建数据库或文件。
- 同一资源被多个 Port 引用时，container `close()` 只关闭一次。

## 临时例外

AST 门禁明确记录两个旧 Web 绕过点：

- `src/diting/web/services/_utils.py`
- `src/diting/web/services/stock.py`

Task 09 必须将例外集合清零，禁止新增第三个例外。
