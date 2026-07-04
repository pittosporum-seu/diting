# 谛听 · 架构设计

> 版本：v2.0 | 日期：2026-07-04 | 状态：设计审查中
> 基于 v1.0 架构审查报告（飞书 JyiRdWYlQoqOPkxETkyc430VnWh）全面重设计

---

## 目录

1. [设计哲学](#1-设计哲学)
2. [设计模式全景](#2-设计模式全景)
3. [分层架构](#3-分层架构)
4. [模块接口协议](#4-模块接口协议)
5. [数据流](#5-数据流)
6. [L0/L1/L2 启动层级](#6-l0l1l2-启动层级)
7. [横切关注点](#7-横切关注点)
8. [目录结构](#8-目录结构)
9. [设计决策记录](#9-设计决策记录)

---

## 1. 设计哲学

### 核心原则

| 原则 | 含义 | 违例信号 |
|------|------|---------|
| **单向依赖** | 下层永远不 import 上层 | data 模块 import 了 analysis 里的东西 |
| **开闭原则** | 加新引擎不改已有代码 | 加一个 CANSLIM 要改 3 个文件 |
| **显式优于隐式** | 跨模块数据用 @dataclass，不用 dict/DataFrame | "这个字段叫 'close' 还是 '收盘价'?" |
| **失败不阻塞** | 一个引擎挂了，其他继续跑 | AI 超时导致整个报告空白 |
| **可观测性优先** | print 不是日志，structlog 才是 | 生产环境出了问题只能靠猜 |

### 命名来源

**谛听** — 地藏菩萨座下神兽，能辨世间万物声音。A股多模型AI投资分析工具，聆听市场多维度信号。

---

## 2. 设计模式全景

### 2.1 模式-问题-方案矩阵

| 设计模式 | 解决什么问题 | 在谛听中的位置 |
|---------|-------------|--------------|
| **Strategy（策略）** | 多种分析引擎统一调用 | `AnalysisEngine.analyze()` → Wyckoff/Buffett/CANSLIM/VolumeProfile |
| **Plugin Registry（插件注册）** | 加新引擎不改已有代码 | `@register_engine("can_slim")` 自动发现 |
| **Chain of Responsibility（责任链）** | 多步骤管道灵活编排 | 数据→信号→分析→评分→报告 管道 |
| **Repository（仓库）** | 隔离数据源细节 | `MarketDataRepository` 屏蔽 mx-data/akshare/DB |
| **Observer（观察者）** | 事件驱动通知 | 信号触发→自动推送飞书/邮件 |
| **Decorator（装饰器）** | 横切关注点不侵入业务 | `@cached`, `@retry`, `@log_latency` |
| **Facade（外观）** | 简化复杂子系统调用 | `Diting.quick_scan()` vs `Diting.deep_analysis()` |
| **Factory（工厂）** | 按名称创建引擎 | `EngineFactory.create("wyckoff")` |
| **Command（命令）** | CLI 操作封装 | 每个 L0/L1/L2 命令 = 一个 Command 对象 |
| **Dependency Injection（依赖注入）** | 解耦模块、方便测试 | 构造函数注入 `DataProvider`，不硬编码 |

### 2.2 核心模式详解

#### Strategy Pattern → 分析引擎统一接口

```python
# 所有分析引擎的共同契约
class AnalysisEngine(ABC):
    """分析引擎抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def analyze(self, context: AnalysisContext) -> AnalysisResult: ...
    
    @abstractmethod
    def required_data(self) -> list[DataType]: ...
```

```
                   ┌────────────────────┐
                   │  AnalysisEngine    │  ← ABC
                   │  + analyze(ctx)    │
                   │  + required_data() │
                   └────────┬───────────┘
           ┌────────┬───────┼───────┬──────────┐
           ▼        ▼       ▼       ▼          ▼
      Wyckoff   Buffett  CANSLIM  Volume    VMD-RSI
      Engine    Scorer    Engine  Profile   Signal
```

每个引擎 = 一个文件 = 一个类，继承 ABC，用 `@register_engine` 自动注册。

#### Plugin Registry Pattern → 开闭原则落地

```python
# 插件注册机制
_engine_registry: dict[str, type[AnalysisEngine]] = {}

def register_engine(name: str):
    """将分析引擎注册到全局注册表"""
    def decorator(cls: type[AnalysisEngine]):
        _engine_registry[name] = cls
        return cls
    return decorator

def discover_engines() -> list[str]:
    """返回所有已注册的引擎名称"""
    return list(_engine_registry.keys())

# 使用：新引擎 = 新建文件 + 继承 ABC + 加装饰器，不碰任何已有代码
@register_engine("can_slim")
class CANSLIMEngine(AnalysisEngine):
    ...
```

#### Chain of Responsibility → 分析管道

```
股票代码 → [数据获取] → [信号处理] → [引擎分析] → [评分融合] → [报告生成] → [推送]
              │              │            │            │            │
              ▼              ▼            ▼            ▼            ▼
         失败→降级       跳过→继续    超时→标记    冲突→仲裁    失败→降级
```

每个环节是独立的 Handler，可插拔、可重排、可跳过。管道配置在 `pipeline.yaml` 中。

#### Repository Pattern → 数据源隔离

```python
class MarketDataRepository:
    """统一数据访问层，屏蔽底层数据源差异"""
    
    def __init__(self, providers: list[DataProvider]):
        self._providers = providers  # 按优先级排序 [MxData, AkShare]
        self._cache = CacheLayer()
    
    def get_realtime(self, symbols: list[str]) -> RealtimeData:
        """获取实时行情，自动降级"""
        for p in self._providers:
            try:
                data = p.fetch_realtime(symbols)
                self._cache.set(f"realtime:{symbols}", data, ttl=3600)
                return data
            except DataUnavailableError:
                continue
        raise AllProvidersFailedError()
```

#### Observer Pattern → 事件驱动推送

```
信号触发事件           订阅者
┌──────────┐       ┌──────────────┐
│RSI＜20   │──→    │ FeishuNotifier│ → 飞书推送
│VMD谷底   │──→    │ EmailNotifier │ → 邮件推送
│大盘暴跌3%│──→    │ AlertManager  │ → 多渠道告警
└──────────┘       └──────────────┘
```

---

## 3. 分层架构

### 3.1 六层架构图

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 5: Presentation（入口/CLI）                           │
│  ┌─────────┐  ┌──────────┐  ┌──────────────┐               │
│  │ CLI     │  │ REST API │  │ Cron Scheduler│              │
│  │ (click) │  │ (FastAPI)│  │ (内置)        │              │
│  └─────────┘  └──────────┘  └──────────────┘               │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: Orchestration（编排层）                            │
│  ┌─────────────────────────────────────────┐                │
│  │           AnalysisPipeline              │                │
│  │  ┌──────┐  ┌──────┐  ┌──────┐  ┌─────┐│                │
│  │  │Fetch │→ │Signal│→ │Engine│→ │Score││                │
│  │  └──────┘  └──────┘  └──────┘  └─────┘│                │
│  └─────────────────────────────────────────┘                │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: Analysis（分析引擎层） ◄── 策略模式核心           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐    │
│  │ Wyckoff  │ │ Buffett  │ │ CANSLIM  │ │Vol Profile │    │
│  │ Engine   │ │ Scorer   │ │ Engine   │ │ Engine     │    │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘    │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Signal Processing（信号处理层）                    │
│  ┌──────┐ ┌────────┐ ┌──────┐ ┌──────────┐ ┌────────┐    │
│  │ VMD  │ │CEEMDAN │ │Wavelet│ │Technical │ │Volume  │    │
│  │      │ │        │ │Denoise│ │Indicators│ │Analysis│    │
│  └──────┘ └────────┘ └──────┘ └──────────┘ └────────┘    │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Data Access（数据访问层） ◄── Repository 模式     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐        │
│  │ MxData   │ │ AkShare  │ │ SQLite   │ │ CSV    │        │
│  │ Provider │ │ Provider │ │ Provider │ │Provider│        │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘        │
│  ┌──────────────────────────────────────────┐              │
│  │            CacheLayer (TTL)              │              │
│  └──────────────────────────────────────────┘              │
├─────────────────────────────────────────────────────────────┤
│  Layer 0: Infrastructure（基础设施层）                       │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌───────────┐           │
│  │Config  │ │Logging │ │Metrics │ │Error      │           │
│  │Manager │ │(struct)│ │(prom)  │ │Hierarchy  │           │
│  └────────┘ └────────┘ └────────┘ └───────────┘           │
└─────────────────────────────────────────────────────────────┘
         ▲
    ┌────┴────┐  横切关注点（所有层可用）
    │ @cached │  @retry  @log_latency  @validate
    └─────────┘
```

### 3.2 依赖方向

```
config ──────────────────────→ 所有层（提供配置）

Layer 0 ──→ 不依赖任何业务层
Layer 1 ──→ L0
Layer 2 ──→ L1 + L0
Layer 3 ──→ L2 + L1   (不碰 L4)
Layer 4 ──→ L3 + L2 + L1  (不碰 L5)
Layer 5 ──→ L4  (通过 Facade)
```

**铁律：下层永远不 import 上层。** 违反 = 架构腐化信号。

---

## 4. 模块接口协议

### 4.1 所有跨模块数据用 @dataclass

```python
# === 数据层协议 ===
@dataclass
class RealtimeQuote:
    symbol: str
    name: str
    price: float
    change_pct: float
    volume: int
    turnover: float
    pe: float | None = None
    pb: float | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: DataSource = DataSource.UNKNOWN

@dataclass 
class HistoricalData:
    symbol: str
    df: Any  # polars DataFrame（明确指定列名）
    columns: list[str]  # 显式声明列名，接收方不用猜
    start_date: date
    end_date: date

# === 信号层协议 ===
@dataclass
class VMDResult:
    symbol: str
    modes: list[np.ndarray]  # K 个模态分量
    cycle_position: float    # 0.0(谷底) ~ 1.0(峰顶)
    trend_slope: float       # 趋势分量斜率
    dominant_period: int     # 主导周期（天）
    timestamp: datetime

@dataclass
class TechnicalSignals:
    symbol: str
    rsi_14: float
    macd: float
    macd_signal: float
    kdj_k: float
    kdj_d: float
    bollinger_position: float  # 0=下轨, 1=上轨
    vwap_deviation: float      # 现价偏离 VWAP 百分比

# === 分析层协议 ===
@dataclass
class AnalysisContext:
    """传给分析引擎的完整上下文"""
    symbol: str
    realtime: RealtimeQuote
    historical: HistoricalData | None = None
    signals: TechnicalSignals | None = None
    vmd: VMDResult | None = None
    fundamentals: dict | None = None  # 财务数据
    holdings: HoldingsInfo | None = None

@dataclass
class AnalysisResult:
    """所有分析引擎的统一输出"""
    engine_name: str
    symbol: str
    score: float  # 0-100
    rating: Rating  # BUY/ACCUMULATE/HOLD/REDUCE/SELL
    signals: list[Signal]
    narrative: str  # AI 生成的文字解读
    charts: list[str]  # base64 或文件路径
    risks: list[str]
    metadata: dict  # 引擎特定的额外数据

# === 管道层协议 ===
@dataclass
class PipelineResult:
    symbols: list[str]
    results: dict[str, list[AnalysisResult]]  # symbol → 各引擎的结果
    consensus: ConsensusScore  # 多引擎共识
    report_path: str
    errors: list[PipelineError]
    duration_ms: int

# === 枚举 ===
class Rating(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    ACCUMULATE = "accumulate"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"

class DataSource(Enum):
    MX_DATA = "mx_data"
    AKSHARE = "akshare"
    SQLITE = "sqlite"
    CSV = "csv"
    UNKNOWN = "unknown"

class DataType(Enum):
    REALTIME = "realtime"
    HISTORICAL = "historical"
    FUNDAMENTALS = "fundamentals"
    FUND_FLOW = "fund_flow"
    MINUTE = "minute"
```

### 4.2 分析引擎注册接口

```python
# 引擎必须实现的接口
class AnalysisEngine(ABC):
    
    @property
    @abstractmethod
    def name(self) -> str:
        """引擎唯一标识，如 'wyckoff', 'buffett'"""
        ...
    
    @property
    @abstractmethod
    def version(self) -> str:
        """引擎版本号"""
        ...
    
    @abstractmethod
    def required_data(self) -> list[DataType]:
        """声明需要的数据类型，管道据此获取数据"""
        ...
    
    @abstractmethod
    def analyze(self, context: AnalysisContext) -> AnalysisResult:
        """执行分析，输入上下文，输出结果"""
        ...
    
    def validate_context(self, context: AnalysisContext) -> bool:
        """可选：验证上下文是否满足要求"""
        required = self.required_data()
        if DataType.HISTORICAL in required and context.historical is None:
            return False
        return True
```

### 4.3 数据提供者接口

```python
class DataProvider(ABC):
    
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    def health_check(self) -> bool:
        """数据源是否可用"""
        ...
    
    @abstractmethod
    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        """获取实时行情"""
        ...
    
    @abstractmethod
    def fetch_historical(self, symbol: str, start: date, end: date) -> HistoricalData:
        """获取历史行情"""
        ...
    
    # 可选方法——不是所有数据源都支持
    def fetch_fundamentals(self, symbol: str) -> dict:
        raise NotImplementedError
    
    def fetch_fund_flow(self, symbol: str) -> dict:
        raise NotImplementedError
    
    def fetch_minute(self, symbol: str, date: date) -> HistoricalData:
        raise NotImplementedError
```

### 4.4 通知渠道接口

```python
class Notifier(ABC):
    
    @property
    @abstractmethod
    def channel_name(self) -> str: ...
    
    @abstractmethod
    async def send(self, message: Notification) -> bool: ...
    
    @abstractmethod
    def health_check(self) -> bool: ...
```

---

## 5. 数据流

### 5.1 完整分析管道

```
入口（CLI / Cron / API）
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 0: 配置加载                                 │
│  Config.load() → .env + watchlist.csv           │
│  判断 L0/L1/L2 运行层级                          │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 1: 数据获取（并行）                          │
│  MarketDataRepository.fetch_all(watchlist)       │
│  ├─ mx-data (主) → 失败降级                      │
│  ├─ akshare (备) → 失败降级                      │
│  └─ SQLite cache (兜底)                          │
│  输出: {symbol: RealtimeQuote + HistoricalData}  │
│  耗时: ~5s (并行)                                 │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 2: 信号处理（并行）                          │
│  for symbol in watchlist:                        │
│    ├─ TechnicalSignals.calculate(df)             │
│    ├─ VMD.decompose(df) → VMDResult              │
│    └─ (可选) Wavelet.denoise(df)                 │
│  输出: {symbol: TechnicalSignals + VMDResult}    │
│  耗时: ~3s/标的（VMD最慢），并行可加速            │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 3: 引擎分析（并行）                          │
│  engines = [w for w in registry if w in config]  │
│  for engine in engines:                          │
│    for symbol in watchlist:                      │
│      context = AnalysisContext(...)               │
│      result = engine.analyze(context)            │
│  输出: {symbol: [AnalysisResult, ...]}           │
│  耗时: ~5-15s/引擎（AI调用最慢）                  │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 4: 评分融合                                 │
│  ConsensusEngine.fuse(all_results)               │
│  ├─ 加权平均（按引擎配置权重）                    │
│  ├─ 冲突检测（两个引擎结论相反时标记）            │
│  └─ 生成 ConsensusScore                          │
│  输出: {symbol: ConsensusScore}                  │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 5: 报告生成                                 │
│  ReportBuilder.build(results, consensus)         │
│  ├─ ECharts 图表                                 │
│  ├─ HTML 单页报告                                │
│  └─ 飞书 Bitable 数据                            │
└─────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────┐
│ Step 6: 推送                                     │
│  for notifier in enabled_notifiers:              │
│    notifier.send(report)                         │
│  ├─ 飞书: 摘要 + 文档链接 + Bitable 链接         │
│  ├─ 邮件: HTML 报告                              │
│  └─ 本地: 保存到 output/                         │
└─────────────────────────────────────────────────┘
```

### 5.2 错误传播策略

```
L1 数据失败
  ├─ mx-data 超时 → 自动切 akshare（降级）
  ├─ akshare 也挂了 → 尝试 SQLite 缓存（兜底）
  └─ 全挂 → 抛出 AllProvidersFailedError，管道终止

L2 信号失败
  ├─ VMD 分解异常（数据不够 50 天）→ 跳过 VMD，标记 result.vmd=None
  └─ 不影响其他信号计算

L3 引擎失败
  ├─ DeepSeek API 超时 → 标记 result.error="AI timeout"，其他引擎继续
  ├─ 引擎抛异常 → 捕获，记录 PipelineError，不阻塞其他引擎
  └─ 所有引擎都挂了 → 生成纯图表报告（无 AI 解读）

L4 评分融合
  ├─ 只有一个引擎成功 → 直接用它的结果
  └─ 全部失败 → 报告只显示 "数据可用，分析不可用"

L5 报告生成
  └─ 失败 → 尝试降级为纯文本报告

L6 推送
  ├─ 飞书失败 → 试邮件
  └─ 全失败 → 本地保存 + 下次重试
```

---

## 6. L0/L1/L2 启动层级

### 6.1 层级定义

| 层级 | 能力 | 数据源 | AI | 推送 | 适用场景 |
|------|------|--------|----|------|---------|
| **L0** | 行情快照+简单指标 | akshare only | ❌ | 本地HTML | 快速扫一眼 |
| **L1** | +AI解读+信号处理 | mx-data + akshare | V4 Flash | 飞书通知 | 日常分析 |
| **L2** | +多引擎共识+深度报告 | mx-data + SQLite缓存 | V4 Pro | 飞书+Bitable+邮件 | 周末复盘 |

### 6.2 实现方式（Command 模式）

```python
# L0: 极简模式，零外部依赖
@cli.command()
@click.option("--watchlist", default="config/watchlist.csv")
def l0(watchlist: str):
    """L0: 快速行情快照"""
    cmd = L0QuickScan(
        data=AkShareProvider(),
        output=LocalSaver("output/"),
    )
    cmd.execute(watchlist)

# L1: 标准模式，AI 辅助
@cli.command()
@click.option("--watchlist", default="config/watchlist.csv")
def l1(watchlist: str):
    """L1: 完整分析+AI解读"""
    cmd = L1StandardAnalysis(
        data=MarketDataRepository([MxDataProvider(), AkShareProvider()]),
        engines=[WyckoffEngine(), BuffettScorer()],
        notifier=FeishuNotifier(),
    )
    cmd.execute(watchlist)

# L2: 全量模式，多引擎共识
@cli.command()
@click.option("--watchlist", default="config/watchlist.csv")
def l2(watchlist: str):
    """L2: 多引擎深度分析"""
    cmd = L2DeepAnalysis(
        data=MarketDataRepository([MxDataProvider(), AkShareProvider()]),
        engines=discover_engines(),  # 所有注册的引擎
        notifiers=[FeishuNotifier(), EmailNotifier(), LocalSaver()],
        report=ReportBuilder(template="deep"),
    )
    cmd.execute(watchlist)
```

### 6.3 层级切换配置

```bash
# .env 中控制
DITING_LEVEL=L1  # L0 | L1 | L2

# 默认命令根据 DITING_LEVEL 自动选择
diting run       # 按 .env 的 LEVEL 执行
diting run --l0  # 强制覆盖为 L0
```

---

## 7. 横切关注点

### 7.1 技术选型总表

| 组件 | 选型 | 说明 |
|------|------|------|
| AI Provider | **LiteLLM**（SDK 模式） | 52K⭐，100+ LLM 统一接口，OpenAI 格式。`pip install litellm` |
| Python 沙箱 | **sandboxmcp**（process 后端） | seccomp + namespace 隔离，资源限制 + 代码验证 + 审计日志。`pip install mcpaisuite-sandboxmcp` |
| 依赖管理 | **uv + pyproject.toml** | 快 10-100x、可复现 |
| 图表 | **ECharts** | 309KB 轻量，iPad 兼容，交互式 |
| 报告 | **单页 HTML** | 移动端友好，飞书可直接分享 |
| 日志 | **structlog** | 结构化日志，可接 Prometheus |

### 7.2 AI Provider 集成（LiteLLM）

```python
from litellm import completion

# 切换 provider 只改 model 字符串，其余代码不变
response = completion(
    model="deepseek/deepseek-v4-pro",  # 或 openai/gpt-4o, anthropic/claude-sonnet-4
    messages=[{"role": "user", "content": "..."}],
    max_tokens=4000,
)

# 支持 100+ provider，包括：
# deepseek/, openai/, anthropic/, gemini/, together_ai/, 
# bedrock/, azure/, huggingface/, replicate/, ...
```

### 7.3 Python 沙箱（sandboxmcp）

```python
from sandboxmcp import Sandbox

# process 模式：零额外依赖，seccomp + namespace 隔离
sandbox = Sandbox(
    backend="process",
    memory_limit_mb=512,
    timeout_seconds=60,
    allowed_imports=["numpy", "pandas", "scipy", "vmdpy"],
    network_enabled=False,
)

# AI 生成代码 → 沙箱执行 → 返回结果 + 审计日志
result = sandbox.run(ai_generated_code)
# → {"output": ..., "errors": [...], "execution_time_ms": 123, "audit_id": "abc"}
```

三层防御：AST 验证 → subprocess 隔离 → seccomp 系统调用过滤（Linux）。

### 7.4 缓存策略
class CacheConfig:
    realtime_ttl: int = 3600    # 实时行情缓存 1 小时
    historical_ttl: int = 86400 # 历史行情缓存 1 天
    financials_ttl: int = 604800 # 财务数据缓存 7 天

# 使用装饰器
@cached(ttl=3600, key="realtime:{symbols}")
def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
    ...
```

### 7.5 结构化日志

```python
import structlog
logger = structlog.get_logger()

# 使用
logger.info("engine.started", engine="wyckoff", symbol="002475")
logger.warning("data.degraded", provider="mx-data", fallback="akshare")
logger.error("analysis.failed", engine="buffett", reason="missing_financials")

# 绝不
print("分析完成")  # ❌
```

### 7.6 重试机制

```python
@retry(max_attempts=3, backoff=2.0, on=[TimeoutError, ConnectionError])
def fetch_from_mx_data(self, symbols: list[str]):
    ...
```

### 7.7 管道监控

```python
@dataclass
class PipelineMetrics:
    total_duration_ms: int
    step_durations: dict[str, int]  # {"fetch": 5200, "signal": 12000, ...}
    engines_succeeded: int
    engines_failed: int
    data_source_used: DataSource
    errors: list[PipelineError]
```

---

## 8. 目录结构

```
diting/
├── docs/                           ← 设计文档
│   ├── 01-design/
│   │   ├── architecture.md         ← 本文档
│   │   ├── features.md             ← 功能设计
│   │   ├── data-models.md          ← 数据模型设计
│   │   ├── api-contracts.md        ← API 契约
│   │   └── development-workflow.md ← 企业级开发流程
│   ├── 02-research/
│   │   ├── wyckoff-method.md       ← 威克夫方法调研
│   │   ├── buffett-munger-a-share.md← 巴菲特/芒格 A 股落地
│   │   ├── analysis-schools-survey.md← 分析模型流派全景调研
│   │   └── signal-processing-methods.md← 信号处理方法调研
│   └── 03-review/
│       └── architecture-review-2026-07-04.md ← 架构审查报告
│
├── src/diting/                     ← 源码
│   ├── __init__.py
│   ├── main.py                     ← CLI 入口 + L0/L1/L2 命令
│   ├── config.py                   ← 配置管理
│   ├── schema.py                   ← 所有 @dataclass 协议
│   ├── enums.py                    ← 枚举定义
│   ├── data/                       ← Layer 1: 数据访问
│   │   ├── __init__.py
│   │   ├── repository.py           ← MarketDataRepository
│   │   ├── providers/
│   │   │   ├── base.py             ← DataProvider ABC
│   │   │   ├── mx_data.py          ← 东方财富
│   │   │   ├── akshare.py          ← akshare 兜底
│   │   │   └── sqlite_cache.py     ← 本地缓存
│   │   └── cache.py                ← TTL 缓存层
│   ├── signals/                    ← Layer 2: 信号处理
│   │   ├── __init__.py
│   │   ├── technical.py            ← RSI/MACD/KDJ/布林
│   │   ├── vmd.py                  ← VMD 分解
│   │   ├── wavelet.py              ← 小波去噪
│   │   └── ceemdan.py              ← CEEMDAN
│   ├── engines/                    ← Layer 3: 分析引擎
│   │   ├── __init__.py             ← 自动发现 & 注册
│   │   ├── base.py                 ← AnalysisEngine ABC
│   │   ├── registry.py             ← 插件注册机制
│   │   ├── wyckoff.py              ← 威克夫 AI 引擎
│   │   ├── buffett.py              ← 巴菲特/芒格（AI + 沙箱）
│   │   ├── can_slim.py             ← CANSLIM 引擎
│   │   ├── volume_profile.py       ← Volume Profile
│   │   └── vmd_rsi.py              ← VMD+RSI 择时
│   ├── pipeline/                   ← Layer 4: 编排
│   │   ├── __init__.py
│   │   ├── runner.py               ← AnalysisPipeline
│   │   ├── consensus.py            ← 多引擎评分融合
│   │   └── pipeline.yaml           ← 管道配置
│   ├── report/                     ← Layer 5: 报告
│   │   ├── __init__.py
│   │   ├── builder.py              ← ReportBuilder
│   │   ├── echarts.py              ← ECharts 图表生成
│   │   ├── templates/
│   │   │   ├── report.html         ← HTML 报告模板
│   │   │   └── email.html          ← 邮件模板
│   │   └── bitable.py              ← 飞书 Bitable 输出
│   ├── notify/                     ← Layer 5: 推送
│   │   ├── __init__.py
│   │   ├── base.py                 ← Notifier ABC
│   │   ├── feishu.py               ← 飞书消息
│   │   ├── email.py                ← 邮件
│   │   └── local.py                ← 本地保存
│   ├── sandbox/                    ← Python 沙箱（sandboxmcp）
│   │   ├── __init__.py
│   │   └── executor.py             ← 执行 AI 代码 + 资源限制 + 审计日志
│   ├── ai/                         ← AI Provider（LiteLLM）
│   │   ├── __init__.py
│   │   └── client.py               ← 统一 completion 接口，一行切 provider
│   └── infra/                      ← 基础设施
│       ├── __init__.py
│       ├── logging_config.py       ← structlog 配置
│       ├── decorators.py           ← @cached @retry @log_latency
│       └── errors.py               ← 异常层次结构
│
├── config/
│   ├── .env.example                ← 环境变量模板（不含真实值）
│   ├── watchlist.example.csv       ← 自选股模板
│   └── pipeline.yaml               ← 管道配置
│
├── tests/                          ← 测试
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── output/                         ← 输出目录（.gitignore）
│
├── pyproject.toml                  ← 项目配置
├── README.md
├── LICENSE                         ← MIT
└── .gitignore
```

---

## 9. 设计决策记录

| # | 决策 | 理由 | 替代方案（被否决） |
|---|------|------|-----------------|
| 1 | 数据协议用 @dataclass，不用 dict | 显式、IDE 补全、类型安全 | dict（太灵活=太容易出错） |
| 2 | 引擎用 ABC + 装饰器注册，不用 if/else | 开闭原则，加引擎不改已有代码 | 在 main.py 里 if engine=='wyckoff' |
| 3 | 数据源用 Repository + 降级，不硬编码 mx-data | 数据源可能不可用，需要降级链 | 只连 mx-data，挂了就报错 |
| 4 | 报告用单页 HTML，不用 PDF | iPad/手机友好、ECharts 交互、飞书可直接分享 | PDF（渲染受限） |
| 5 | 日志用 structlog，不用 print | 结构化、可搜索、可接 Prometheus | print（生产环境盲人） |
| 6 | 管道配置用 YAML，不用 Python 硬编码 | 非开发人员可调整策略 | 写死在代码里 |
| 7 | 项目放本地 workspace，不在同步文件夹 | 代码项目含 venv/node_modules，不适合云同步 | ObsidianVault（同步文件夹会产生大量冲突文件） |
| 8 | pyproject.toml + uv 管理依赖 | 现代化、快速、可复现 | pip + requirements.txt |
| 9 | MIT License | 开源友好，最小限制 | GPL（传播限制多） |
| 10 | 计算任务交给 AI + Python 沙箱 | AI 规划计算逻辑、沙箱执行（sandboxmcp），可审计、防幻觉 | 本地硬编码计算逻辑；纯 LLM 直接输出数值 |
| 11 | AI Provider 用 LiteLLM，不自己写适配层 | 52K⭐成熟项目，100+ provider 统一 OpenAI 格式，`pip install litellm` 即用 | 自己为每个 provider 写 SDK 适配（维护成本高） |
| 12 | 沙箱用 sandboxmcp，不造轮子 | seccomp+namespace 隔离 + 资源限制 + 审计日志 + AST 验证，开箱即用 | subprocess 手动限制（功能不全）；Docker（太重） |

---

*文档维护：小爪 | 谛听项目组 | 2026-07-04*
