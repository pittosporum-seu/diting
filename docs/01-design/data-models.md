# 谛听 · 数据模型设计

> 版本：v1.0 | 日期：2026-07-04 | 状态：设计阶段

---

## 设计原则

1. **显式优于隐式**：所有跨模块数据用 `@dataclass`，不用 dict/DataFrame 裸传
2. **类型安全**：必填/可选字段用类型标注明确区分
3. **不可变优先**：数据对象创建后不应被修改
4. **来源可追溯**：每个数据点标注 `source` 和 `timestamp`

---

## 核心实体

### RealtimeQuote（实时行情）

```python
@dataclass(frozen=True)
class RealtimeQuote:
    symbol: str           # 代码: "002475"
    name: str             # 名称: "立讯精密"
    price: float          # 最新价
    change_pct: float     # 涨跌幅(%)
    open: float           # 开盘价
    high: float           # 最高价
    low: float            # 最低价
    volume: int           # 成交量(手)
    turnover: float       # 成交额(元)
    pe: float | None      # 市盈率（可能缺失）
    pb: float | None      # 市净率
    total_mv: float | None # 总市值
    timestamp: datetime   # 数据时间
    source: DataSource    # 数据来源
```

### HistoricalData（历史行情）

```python
@dataclass(frozen=True)
class HistoricalData:
    symbol: str
    df: pl.DataFrame      # polars DataFrame
    columns: list[str]     # 显式列名: ["date","open","high","low","close","volume"]
    start_date: date
    end_date: date
    source: DataSource
    has_weekend_data: bool = False  # mx-data 可能包含非交易日
```

### Financials（财务数据）

```python
@dataclass(frozen=True)
class Financials:
    symbol: str
    report_date: date     # 报告期
    revenue: float        # 营业收入
    revenue_yoy: float    # 营收同比(%)
    net_profit: float     # 归母净利润
    profit_yoy: float     # 利润同比(%)
    gross_margin: float   # 毛利率(%)
    net_margin: float     # 净利率(%)
    roe: float            # ROE(%)
    debt_ratio: float     # 资产负债率(%)
    current_ratio: float  # 流动比率
    quick_ratio: float    # 速动比率
    fcf: float | None     # 自由现金流
    op_cash_flow: float | None
    source: DataSource
```

### FundFlow（资金流向）

```python
@dataclass(frozen=True)
class FundFlow:
    symbol: str
    date: date
    main_net_inflow: float    # 主力净流入
    super_large_net: float    # 超大单净流入
    large_net: float           # 大单净流入
    medium_net: float          # 中单净流入
    small_net: float           # 小单净流入
    ddx: float                 # DDX 指标
    ddy: float                 # DDY 指标
    ddz: float                 # DDZ 指标
    margin_balance: float | None  # 融资余额
    margin_buy: float | None      # 融资买入额
```

### VMDResult（VMD 分解结果）

```python
@dataclass(frozen=True)
class VMDResult:
    symbol: str
    modes: tuple             # K 个模态分量（tuple 用于 hashable）
    cycle_position: float    # 0.0(谷底) ~ 1.0(峰顶)
    trend_slope: float       # 趋势分量斜率
    dominant_period: int     # 主导周期（天）
    trend_broken: bool       # 趋势是否破坏
    timestamp: datetime
    params: dict             # VMD 参数 {K, alpha, tau, window}
```

### TechnicalSignals（技术信号）

```python
@dataclass(frozen=True)
class TechnicalSignals:
    symbol: str
    rsi_14: float
    macd: float
    macd_signal_line: float
    macd_histogram: float
    kdj_k: float
    kdj_d: float
    kdj_j: float
    bollinger_upper: float
    bollinger_middle: float
    bollinger_lower: float
    bollinger_position: float  # 0=下轨, 0.5=中轨, 1=上轨
    ma_5: float
    ma_20: float
    ma_60: float
    vwap: float
    vwap_deviation: float      # 现价偏离 VWAP(%)
    volume_ratio: float        # 量比(当前/5日均量)
    timestamp: datetime
```

---

## 分析管道实体

### AnalysisContext（分析上下文）

```python
@dataclass(frozen=True)
class AnalysisContext:
    """传给分析引擎的完整上下文"""
    symbol: str
    realtime: RealtimeQuote
    historical: HistoricalData | None = None
    signals: TechnicalSignals | None = None
    vmd: VMDResult | None = None
    financials: Financials | None = None
    fund_flow: FundFlow | None = None
```

### AnalysisResult（分析结果）

```python
@dataclass(frozen=True)
class AnalysisResult:
    engine_name: str          # "wyckoff" / "buffett" / "can_slim"
    engine_version: str       # "1.0.0"
    symbol: str
    score: float              # 0-100
    rating: Rating
    signals: tuple[Signal, ...]  # 触发的信号列表
    narrative: str            # AI 生成的文字解读（Markdown）
    charts: tuple[str, ...]   # base64 图片或文件路径
    risks: tuple[str, ...]    # 风险提示
    confidence: float         # 置信度 0-1
    computation_log: str      # Python 沙箱执行日志（可审计）
    metadata: dict            # 引擎特定数据
    error: str | None = None  # 如果失败，错误信息
    duration_ms: int = 0
```

### ConsensusScore（多引擎共识）

```python
@dataclass(frozen=True)
class ConsensusScore:
    symbol: str
    weighted_score: float     # 加权综合评分
    rating: Rating
    engines_used: tuple[str, ...]
    engines_failed: tuple[str, ...]
    conflicts: tuple[Conflict, ...]  # 引擎间矛盾
    confidence: float

@dataclass(frozen=True)
class Conflict:
    engine_a: str
    engine_b: str
    a_rating: Rating
    b_rating: Rating
    severity: str  # "mild"(相邻) | "moderate"(跳一档) | "severe"(完全相反)
```

### PipelineResult（管道输出）

```python
@dataclass
class PipelineResult:
    symbols: tuple[str, ...]
    results: dict[str, tuple[AnalysisResult, ...]]
    consensus: dict[str, ConsensusScore]
    reports: dict[str, str]     # "html": path, "pdf": path
    errors: tuple[PipelineError, ...]
    metrics: PipelineMetrics
```

---

## 枚举定义

```python
class Rating(Enum):
    STRONG_BUY = "strong_buy"   # 强烈买入 (>80)
    BUY = "buy"                  # 买入 (65-80)
    ACCUMULATE = "accumulate"    # 增持 (55-65)
    HOLD = "hold"                # 持有 (45-55)
    REDUCE = "reduce"            # 减持 (35-45)
    SELL = "sell"                # 卖出 (<35)

class DataSource(Enum):
    MX_DATA = "mx_data"          # 东方财富 mx-data
    AKSHARE = "akshare"          # akshare 免费接口
    SQLITE = "sqlite"            # 本地缓存 DB
    CSV = "csv"                  # CSV 文件
    CACHE = "cache"              # TTL 内存缓存
    UNKNOWN = "unknown"

class Signal(Enum):
    # VMD 信号
    VMD_TROUGH = "vmd_trough"        # 谷底
    VMD_PEAK = "vmd_peak"            # 峰顶
    VMD_TREND_BROKEN = "vmd_trend_broken"

    # RSI 信号
    RSI_OVERSOLD = "rsi_oversold"     # <30
    RSI_OVERBOUGHT = "rsi_overbought" # >70

    # Wyckoff 信号
    WYCKOFF_SPRING = "wyckoff_spring"
    WYCKOFF_SOS = "wyckoff_sos"

    # 量价信号
    VOLUME_SURGE = "volume_surge"     # 放量
    VOLUME_DRIED = "volume_dried"     # 缩量

    # 资金信号
    FUND_INFLOW = "fund_inflow"       # 资金流入
    FUND_OUTFLOW = "fund_outflow"
```

---

## 数据质量标注

每个数据实体自带质量元数据：

```python
@dataclass(frozen=True)
class DataQuality:
    grade: str  # A/B/C/D
    age_seconds: int  # 数据时效（秒）
    source: DataSource
    note: str = ""
```

- **A**：实时接口返回，时效 <60s  
- **B**：实时接口返回，时效 <1h  
- **C**：缓存/备份数据，时效 <24h  
- **D**：数据缺失或冲突，不可用于精确判断

---

*文档维护：小爪 | 谛听项目组 | 2026-07-04*
