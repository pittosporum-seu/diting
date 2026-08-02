# v0.8.0 Task 02 完成报告

## 结论

v0.8 领域协议和外部能力 Ports 已建立。

- 新增 `FetchMode`、缓存/trace/run/profile/strategy 枚举。
- 新增冻结 `DataResult[T]`、`CacheInfo`、`ProviderTrace`、请求对象、规范化历史 bars、证券目录、交易日历、数据快照、EngineRun、AnalysisRun、ScanResult 和策略版本。
- 失败 EngineRun 与 AnalysisRun 的评分默认为 `None`，不再以 50 分表达失败。
- 新增 DataGateway、MarketDataProvider、CacheStore、DurableStore、LLM、Sandbox、Clock、Calendar、Report 和 Notifier Protocol。
- `ports.py` 不导入 FastAPI、LiteLLM、akshare 或任何具体 Provider。

## 验证

- schema/ports 聚焦测试：22 passed。
- 冻结性、请求模式、typed bars、失败评分语义、策略生命周期和 runtime Protocol 均有覆盖。
- 独立子进程导入 `src.diting.ports`，可选依赖和 adapter 模块均未进入 `sys.modules`。

## 风险

旧 `HistoricalData.df` 为兼容历史管道暂时保留；新 DataGateway Port 只接受 `HistoricalSeries.bars`。Task 07/09 完成后旧 DataFrame 跨层契约必须退出主流程。
