# 谛听 · v0.2.1 全量配置化设计方案

> 将硬编码参数全部抽到 `config/diting.yaml`，实现配置驱动运行时。
> 日期：2026-07-07 | 版本：v0.2.1 | 状态：设计阶段 🟡

---

## 一、设计哲学

### 三层配置体系

```
优先级：CLI 参数 > 环境变量 (.env) > 配置文件 (diting.yaml) > 代码默认值
```

| 层 | 存放什么 | 格式 |
|---|---------|:----:|
| **CLI 参数** | 用户每次运行时想改的（`--port 9000`） | CLI flag |
| **环境变量** | 密钥、开关（`MX_APIKEY`、`DITING_LOG`） | `.env` |
| **配置文件** | 结构化策略（降级链、权重、参数） | **`config/diting.yaml`** 🎯 |
| **代码默认值** | 合理的后备值 | Python 常量 |

### 合并规则

```
最终值 = CLI参数 or env_var or yaml_value or code_default
```

---

## 二、配置文件：`config/diting.yaml`

**一个文件管所有，约 80 行。** 文件不存在时 → 全部用代码默认值，完全向后兼容。

```yaml
# config/diting.yaml — 谛听主配置文件
# 此文件不存在时所有模块使用代码默认值

# ── 数据源降级链 ──────────────────────────────────

providers:
  - name: eltdx          # 通达信直连（最快）
    priority: 10
    auto_detect: true    # 启动时检测可用性
  - name: ashare         # 新浪/腾讯免费数据
    priority: 20
    auto_detect: false
  - name: mx_data        # 东方财富（需 API Key）
    priority: 30
    requires_key: MX_APIKEY
    settings:
      max_batch: 4       # 每批最多查 4 只
  - name: akshare        # 兜底（慢但全）
    priority: 40
    auto_detect: false

# ── 引擎选择 + 权重 ────────────────────────────────

engines:
  default:               # 默认启用哪些引擎（按顺序）
    - verdict            # 结论翻译（必选）
    - vmd_rsi            # VMD+RSI 择时
    - volume_profile     # 成交量分布
    # - wyckoff          # 以下需 AI，当前不可用时自动跳过
    # - buffett
    # - can_slim

  weights:
    vmd_rsi: 1.2
    verdict: 1.0
    volume_profile: 0.8
    wyckoff: 0.6
    buffett: 0.6
    can_slim: 0.5

  scoring:
    threshold: [80, 65, 50, 35, 20]  # strong_buy/buy/accumulate/hold/reduce

# ── 技术指标参数 ──────────────────────────────────

indicators:
  rsi:      {period: 14, oversold: 30, overbought: 75}
  macd:     {fast: 12, slow: 26, signal: 9}
  kdj:      {period: 9, k_smooth: 3, d_smooth: 3}
  bollinger:{period: 20, std_dev: 2.0}
  vmd:      {k: 6, alpha: 2000, min_window: 60, trough: 0.3, peak: 0.7}
  ma:       [5, 20, 60]

# ── 管道运行参数 ──────────────────────────────────

pipeline:
  max_workers: 4
  timeout_per_engine: 60   # 秒
  fail_fast: false

  cache:
    realtime_ttl: 300      # 实时行情缓存 5 分钟
    historical_ttl: 3600   # 历史行情缓存 1 小时
    max_size: 512

  logging: WARNING

# ── 报告配置 ──────────────────────────────────────

report:
  level: L2
  theme: light
  output_dir: ./output/
  charts: {width: 800, height: 400}

# ── 通知通道 ──────────────────────────────────────

notify:
  default_channel: local
  channels:
    feishu:
      enabled: false
      settings: {}
    email:
      enabled: false
      settings: {}
```

---

## 三、核心集成：ConfigLoader

```python
# src/diting/infra/config_loader.py 🆕

from pathlib import Path
from typing import Any
import yaml

class ConfigLoader:
    """统一配置加载器。

    读取 config/diting.yaml，支持：
    - 文件不存在 → 返回空 dict，各模块用代码默认值
    - 字段缺失 → 模块用代码默认值
    - 惰性加载 + 缓存
    """

    _config: dict | None = None

    @classmethod
    def get(cls, root: Path | None = None) -> dict:
        """加载 diting.yaml（惰性，缓存结果）"""
        if cls._config is not None:
            return cls._config
        path = (root or Path.cwd()) / "config" / "diting.yaml"
        if not path.exists():
            cls._config = {}
            return cls._config
        with open(path) as f:
            cls._config = yaml.safe_load(f) or {}
        return cls._config

    @classmethod
    def get_section(cls, section: str, root: Path | None = None) -> dict:
        """获取某个配置段落，如 get_section('providers')"""
        return cls.get(root).get(section, {})
```

---

## 四、各模块集成方式

### 4.1 数据源 — `main.py` + `data/providers/`

```python
# 旧：硬编码
def _build_repo(cfg):
    providers = []
    if cfg.mx_apikey:
        providers.append(MxDataProvider(api_key=cfg.mx_apikey))
    providers.append(AkShareProvider())
    return MarketDataRepository(providers=providers)

# 新：配置驱动
def _build_repo(cfg):
    provider_configs = ConfigLoader.get_section("providers")
    providers = ProviderFactory.from_config(provider_configs, cfg)
    return MarketDataRepository(providers=providers)
```

### 4.2 引擎 — `main.py` + `pipeline/consensus.py`

```python
# 旧：discover_engines()[:3]  权重一律 1.0
# 新：
engine_cfg = ConfigLoader.get_section("engines")
engines = engine_cfg.get("default", discover_engines())
weights = engine_cfg.get("weights", {})
thresholds = engine_cfg.get("scoring", {}).get("threshold", [80, 65, 50, 35, 20])
```

### 4.3 技术指标 — `signals/technical.py` + `signals/vmd.py`

```python
# 旧：_rsi(close, 14)  硬编码
# 新：
ind_cfg = ConfigLoader.get_section("indicators")
rsi_period = ind_cfg.get("rsi", {}).get("period", 14)
_vmd_k = ind_cfg.get("vmd", {}).get("k", 6)
```

### 4.4 管道 — `pipeline/runner.py` + `data/cache.py`

```python
pipe_cfg = ConfigLoader.get_section("pipeline")
max_workers = pipe_cfg.get("max_workers", 4)
```

### 4.5 报告 — `report/builder.py`

```python
report_cfg = ConfigLoader.get_section("report")
level = report_cfg.get("level", "L2")
```

---

## 五、目录结构变化

```
config/
├── diting.yaml           🆕  ← 主配置文件（约 80 行）
├── .env.example          ← 已有（环境变量模板）
└── watchlist.example.csv ← 已有

src/diting/
└── infra/
    └── config_loader.py  🆕  ← YAML 加载器（约 60 行）
```

**删掉：** `config/pipeline.yaml`（空文件，没内容）

---

## 六、ProviderFactory

```python
# data/providers/eltdx.py 🆕 — 约 80 行
from .base import DataProvider

class ELtdxProvider(DataProvider):
    name = "eltdx"
    priority = 10

    def health_check(self) -> bool:
        try:
            self._client()
            return True
        except Exception:
            return False

    def fetch_realtime(self, symbols) -> dict[str, RealtimeQuote]:
        ...

# data/providers/ashare.py 🆕 — 约 50 行（内联 Ashare 源码）
# 单文件实现，不依赖外部 pip 包

# data/providers/base.py ✏️ +10 行
class DataProvider(ABC):
    # ...
    @classmethod
    def from_config(cls, name: str, settings: dict | None = None):
        """根据名称和配置创建 provider 实例"""
        ...
```

---

## 七、迁移策略

向后兼容：文件不存在 → `ConfigLoader.get()` 返回 `{}` → 所有模块用代码默认值。**现有功能无任何影响。**

### Phase 1：基础设施
1. `infra/config_loader.py` — YAML 加载器
2. `data/providers/base.py` — 加 `from_config()`  
3. `data/providers/eltdx.py` — 通达信 provider
4. `data/providers/ashare.py` — 免费数据 provider
5. `config/diting.yaml` — 配置文件

### Phase 2：数据源接入
6. `main.py._build_repo()` — 配置驱动
7. 跑通 `diting 002475`

### Phase 3：引擎 + 指标
8. `pipeline/consensus.py` — 引擎权重 + 阈值
9. `signals/technical.py` + `signals/vmd.py` — 指标参数

### Phase 4：管道 + 报告
10. `pipeline/runner.py` + `data/cache.py`
11. `report/builder.py`
12. 全量集成测试

---

## 八、改动统计

| 文件 | 操作 | 行数 |
|------|:----:|:----:|
| `config/diting.yaml` | 🆕 | ~80 |
| `infra/config_loader.py` | 🆕 | ~60 |
| `data/providers/eltdx.py` | 🆕 | ~80 |
| `data/providers/ashare.py` | 🆕 | ~50 |
| `data/providers/base.py` | ✏️ | +15 |
| `data/repository.py` | ✏️ | —（不用改） |
| `config.py` | ✏️ | +20 |
| `main.py` | ✏️ | -30 |
| `pipeline/consensus.py` | ✏️ | +20 |
| `pipeline/runner.py` | ✏️ | +10 |
| `signals/vmd.py` | ✏️ | +10 |
| `signals/technical.py` | ✏️ | +15 |
| `report/builder.py` | ✏️ | +10 |
| `config/pipeline.yaml` | 🗑️ 删除 | — |
| **合计** | | **~340 行新增 / -30 行删减** |

---

*文档维护：小爪 | 谛听项目组 | 2026-07-07*
*版本：v0.2.1 | 状态：设计阶段 🟡 | 待确认后进入开发*
