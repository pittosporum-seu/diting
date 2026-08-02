"""Strict v0.8 application configuration and legacy watchlist access."""

from __future__ import annotations

import csv
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from .infra.errors import ConfigError
from .infra.logging_config import get_logger

logger = get_logger(__name__)


class _StrictModel(BaseModel):
    """Immutable model that rejects misspelled or unsupported fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderSettings(_StrictModel):
    max_batch: int = Field(default=4, ge=1, le=100)


class ProviderConfig(_StrictModel):
    name: str
    priority: int = Field(default=100, ge=0)
    auto_detect: bool = False
    requires_key: str | None = None
    settings: ProviderSettings = Field(default_factory=ProviderSettings)


class EngineScoringConfig(_StrictModel):
    threshold: tuple[float, float, float, float, float] = (80, 65, 50, 35, 20)


class EngineConfig(_StrictModel):
    default: tuple[str, ...] = (
        "technical",
        "volume_profile",
        "wyckoff",
        "can_slim",
    )
    deep: tuple[str, ...] = (
        "technical",
        "volume_profile",
        "wyckoff",
        "can_slim",
        "buffett",
    )
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "technical": 1.0,
            "volume_profile": 0.8,
            "wyckoff": 0.8,
            "can_slim": 0.7,
            "buffett": 0.7,
            "vmd_rsi": 0.0,
        }
    )
    scoring: EngineScoringConfig = Field(default_factory=EngineScoringConfig)


class VMDCycleConfig(_StrictModel):
    k: int = Field(default=8, ge=2)
    alpha: int = Field(default=2000, ge=1)
    window: int = Field(default=250, ge=20)
    tol: float = Field(default=1e-5, gt=0)


class ContextConfig(_StrictModel):
    providers: tuple[str, ...] = ("price_basic", "vmd_cycle_state")
    vmd_cycle_state: VMDCycleConfig = Field(default_factory=VMDCycleConfig)


class RSIConfig(_StrictModel):
    period: int = Field(default=14, ge=2)
    oversold: float = 30
    overbought: float = 75


class MACDConfig(_StrictModel):
    fast: int = Field(default=12, ge=1)
    slow: int = Field(default=26, ge=2)
    signal: int = Field(default=9, ge=1)


class KDJConfig(_StrictModel):
    period: int = Field(default=9, ge=2)
    k_smooth: int = Field(default=3, ge=1)
    d_smooth: int = Field(default=3, ge=1)


class BollingerConfig(_StrictModel):
    period: int = Field(default=20, ge=2)
    std_dev: float = Field(default=2.0, gt=0)


class VMDIndicatorConfig(_StrictModel):
    k: int = Field(default=6, ge=2)
    alpha: int = Field(default=2000, ge=1)
    min_window: int = Field(default=60, ge=20)
    trough: float = Field(default=0.3, ge=0, le=1)
    peak: float = Field(default=0.7, ge=0, le=1)


class IndicatorConfig(_StrictModel):
    rsi: RSIConfig = Field(default_factory=RSIConfig)
    macd: MACDConfig = Field(default_factory=MACDConfig)
    kdj: KDJConfig = Field(default_factory=KDJConfig)
    bollinger: BollingerConfig = Field(default_factory=BollingerConfig)
    vmd: VMDIndicatorConfig = Field(default_factory=VMDIndicatorConfig)
    ma: tuple[int, ...] = (5, 20, 60)


class PipelineCacheConfig(_StrictModel):
    realtime_ttl: int = Field(default=30, ge=1)
    historical_ttl: int = Field(default=300, ge=1)
    max_size: int = Field(default=512, ge=1)


class PipelineConfig(_StrictModel):
    max_workers: int = Field(default=4, ge=1, le=32)
    llm_concurrent: int = Field(default=2, ge=1, le=16)
    scan_concurrent: int = Field(default=1, ge=1, le=4)
    queue_limit: int = Field(default=100, ge=1)
    timeout_per_engine: int = Field(default=60, ge=1)
    fail_fast: bool = False
    ai_batch_size: int = Field(default=15, ge=1)
    deep_concurrent: int = Field(default=4, ge=1)
    cache: PipelineCacheConfig = Field(default_factory=PipelineCacheConfig)
    logging: str = "WARNING"


class ChartConfig(_StrictModel):
    width: int = Field(default=800, ge=1)
    height: int = Field(default=400, ge=1)


class ReportConfig(_StrictModel):
    level: str = "L2"
    theme: Literal["light", "dark"] = "light"
    output_dir: Path = Path("output")
    charts: ChartConfig = Field(default_factory=ChartConfig)


class NotifyChannelConfig(_StrictModel):
    enabled: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)


class NotifyConfig(_StrictModel):
    default_channel: str = "local"
    channels: dict[str, NotifyChannelConfig] = Field(default_factory=dict)


class AnalysisPrefetchConfig(_StrictModel):
    enabled: bool = True
    idle_hour: int = Field(default=18, ge=0, le=23)
    batch_size: int = Field(default=3, ge=1)
    stock_delay: int = Field(default=3, ge=0)
    batch_delay: int = Field(default=20, ge=0)
    max_stocks: int = Field(default=30, ge=1)
    signal_threshold: float = Field(default=65, ge=0, le=100)


class PrefetchConfig(_StrictModel):
    analysis: AnalysisPrefetchConfig = Field(default_factory=AnalysisPrefetchConfig)


class RuntimeConfig(_StrictModel):
    environment: Literal["development", "test", "production"] = "development"
    public_readonly: bool = False
    log_level: str = "WARNING"


class DatabaseConfig(_StrictModel):
    business_path: Path = Path("diting.db")
    cache_path: Path = Path("diting_cache.db")


class SecurityConfig(_StrictModel):
    owner_token_hash: SecretStr | None = None
    session_secret: SecretStr | None = None
    allowed_origins: tuple[str, ...] = ()
    session_hours: int = Field(default=12, ge=1, le=168)


class AIConfig(_StrictModel):
    enabled: bool = True
    model: str = "deepseek/deepseek-v4-pro"
    api_key: SecretStr | None = None
    sandbox_enabled: bool = False


class CredentialConfig(_StrictModel):
    mx_api_key: SecretStr | None = None


class StrategyConfig(_StrictModel):
    selected: str = "mean_reversion_v1"
    require_active: bool = True


class AppConfig(_StrictModel):
    """Complete validated application configuration snapshot."""

    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    credentials: CredentialConfig = Field(default_factory=CredentialConfig)
    providers: tuple[ProviderConfig, ...] = (
        ProviderConfig(name="ashare", priority=20),
        ProviderConfig(name="mx_data", priority=30, requires_key="MX_APIKEY"),
        ProviderConfig(name="akshare", priority=40),
    )
    engines: EngineConfig = Field(default_factory=EngineConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    prefetch: PrefetchConfig = Field(default_factory=PrefetchConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    services: dict[str, str] = Field(default_factory=dict)


_ENV_PATHS: dict[str, tuple[str, ...]] = {
    "DITING_ENVIRONMENT": ("runtime", "environment"),
    "DITING_PUBLIC_READONLY": ("runtime", "public_readonly"),
    "DITING_LOG": ("runtime", "log_level"),
    "DITING_DB_PATH": ("database", "business_path"),
    "DITING_CACHE_DB_PATH": ("database", "cache_path"),
    "DITING_REPORT_OUTPUT_DIR": ("report", "output_dir"),
    "DITING_OWNER_TOKEN_HASH": ("security", "owner_token_hash"),
    "DITING_SESSION_SECRET": ("security", "session_secret"),
    "DITING_ALLOWED_ORIGINS": ("security", "allowed_origins"),
    "AI_MODEL": ("ai", "model"),
    "AI_API_KEY": ("ai", "api_key"),
    "DITING_AI_ENABLED": ("ai", "enabled"),
    "DITING_SANDBOX_ENABLED": ("ai", "sandbox_enabled"),
    "MX_APIKEY": ("credentials", "mx_api_key"),
    "NOTIFY_DEFAULT": ("notify", "default_channel"),
}

_YAML_SECRET_PATHS: tuple[tuple[str, ...], ...] = (
    ("security", "owner_token_hash"),
    ("security", "session_secret"),
    ("ai", "api_key"),
    ("credentials", "mx_api_key"),
)


def _deep_merge(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for key, value in incoming.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _deep_merge(current, value)
        else:
            target[key] = value


def _set_path(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = target
    for part in path[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[path[-1]] = value


def _path_is_set(source: Mapping[str, Any], path: tuple[str, ...]) -> bool:
    cursor: Any = source
    for part in path:
        if not isinstance(cursor, Mapping) or part not in cursor:
            return False
        cursor = cursor[part]
    return cursor not in (None, "")


def _normalise_override_map(overrides: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in overrides.items():
        if "." in key:
            _set_path(result, tuple(key.split(".")), value)
        elif isinstance(value, Mapping):
            result[key] = dict(value)
        else:
            result[key] = value
    return result


def load_app_config(
    path: Path | str | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load defaults < YAML < environment < explicit overrides."""

    config_path = Path(path) if path is not None else Path("config/diting.yaml")
    raw: dict[str, Any] = {}
    if config_path.exists():
        try:
            with config_path.open(encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"无法读取配置 {config_path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"配置根节点必须是对象: {config_path}")
        forbidden = [".".join(item) for item in _YAML_SECRET_PATHS if _path_is_set(loaded, item)]
        if forbidden:
            raise ConfigError("密钥字段只能通过环境变量注入: " + ", ".join(forbidden))
        _deep_merge(raw, loaded)

    if environ is None:
        import os

        environ = os.environ
    env_values: dict[str, Any] = {}
    for env_name, field_path in _ENV_PATHS.items():
        if env_name not in environ:
            continue
        value: Any = environ[env_name]
        if env_name == "DITING_ALLOWED_ORIGINS":
            value = tuple(item.strip() for item in value.split(",") if item.strip())
        _set_path(env_values, field_path, value)
    _deep_merge(raw, env_values)

    if overrides:
        _deep_merge(raw, _normalise_override_map(overrides))

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"配置校验失败: {exc}") from exc


class Config:
    """Compatibility facade for watchlist migration and legacy key reads."""

    WATCHLIST_REQUIRED_COLS = {"code", "name", "market"}
    _CODE_PATTERN = re.compile(r"^\d{6}$")
    _MARKET_PATTERN = re.compile(r"^(sz|sh|bj)$")

    def __init__(
        self,
        project_root: Path | None = None,
        db_path: str | None = None,
        settings: AppConfig | None = None,
    ) -> None:
        if settings is None:
            from .infra.config_loader import ConfigLoader

            settings = ConfigLoader.current()
        self.settings = settings
        self._root = project_root or Path.cwd()
        self._watchlist_db = None
        self._db_path = db_path

    @staticmethod
    def _secret_value(value: SecretStr | None) -> str:
        return value.get_secret_value() if value is not None else ""

    def get(self, key: str, default: str = "") -> str:
        values = {
            "DITING_LEVEL": self.settings.report.level,
            "DITING_LOG": self.settings.runtime.log_level,
            "AI_MODEL": self.settings.ai.model,
            "AI_API_KEY": self._secret_value(self.settings.ai.api_key),
            "MX_APIKEY": self._secret_value(self.settings.credentials.mx_api_key),
            "NOTIFY_DEFAULT": self.settings.notify.default_channel,
        }
        return values.get(key, default)

    @property
    def level(self) -> str:
        return self.get("DITING_LEVEL", "L1")

    @property
    def ai_model(self) -> str:
        return self.get("AI_MODEL", "deepseek/deepseek-v4-pro")

    @property
    def ai_api_key(self) -> str:
        return self.get("AI_API_KEY")

    @property
    def mx_apikey(self) -> str:
        return self.get("MX_APIKEY")

    @property
    def notify_default(self) -> str:
        return self.get("NOTIFY_DEFAULT", "local")

    def _get_watchlist_db(self):
        if self._watchlist_db is None:
            from .storage import WatchlistDB

            self._watchlist_db = WatchlistDB(db_path=self._db_path)
        return self._watchlist_db

    def load_watchlist(
        self, path: str | None = None, validate: bool = True
    ) -> list[dict[str, Any]]:
        """Load the watchlist from SQLite, migrating the legacy CSV when needed."""

        db = self._get_watchlist_db()
        rows = db.list()
        if rows:
            return rows

        filepath = Path(path) if path else self._root / "config" / "watchlist.csv"
        if not filepath.exists():
            logger.warning("config.watchlist.empty_all")
            return []

        with filepath.open(newline="", encoding="utf-8") as handle:
            csv_rows = list(csv.DictReader(handle))
        if not csv_rows:
            logger.warning("config.watchlist.empty", path=str(filepath))
            return []

        if validate:
            self._validate_watchlist(csv_rows, str(filepath))
        imported = db.migrate_from_csv(filepath)
        return db.list() if imported > 0 else []

    @classmethod
    def _validate_watchlist(cls, rows: list[dict[str, Any]], path: str) -> None:
        errors: list[str] = []
        for line_number, row in enumerate(rows, start=2):
            cleaned = {
                key.strip(): value.strip() if isinstance(value, str) else value
                for key, value in row.items()
                if key is not None
            }
            for column in cls.WATCHLIST_REQUIRED_COLS:
                if not cleaned.get(column):
                    errors.append(f"行{line_number}: 缺少必填列 '{column}'")

            code = cleaned.get("code", "")
            market = cleaned.get("market", "").lower()
            if code and not cls._CODE_PATTERN.match(code):
                errors.append(f"行{line_number}: 代码 '{code}' 格式错误，应为6位数字")
            if market and not cls._MARKET_PATTERN.match(market):
                errors.append(f"行{line_number}: 市场 '{market}' 无效，应为 sz/sh/bj")

        if errors:
            raise ConfigError(f"watchlist 验证失败 ({path}):\n" + "\n".join(errors))
