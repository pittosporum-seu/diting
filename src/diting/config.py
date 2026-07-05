"""谛听 · 配置管理 — #9 watchlist 验证增强"""

import csv
import os
import re
from pathlib import Path
from typing import Any

from .infra.errors import ConfigError
from .infra.logging_config import get_logger

logger = get_logger(__name__)


class Config:
    """应用配置，从 .env 和 watchlist.csv 加载"""

    # 自选股 CSV 必填列
    WATCHLIST_REQUIRED_COLS = {"code", "name", "market"}

    # 代码格式验证
    _CODE_PATTERN = re.compile(r"^\d{6}$")
    _MARKET_PATTERN = re.compile(r"^(sz|sh|bj)$")

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()
        self._data: dict[str, str] = {}
        self._load_env()

    def _load_env(self) -> None:
        env_file = self._root / ".env"
        if not env_file.exists():
            return
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key not in os.environ:
                    self._data[key] = val

    def get(self, key: str, default: str = "") -> str:
        return os.environ.get(key) or self._data.get(key, default)

    @property
    def level(self) -> str:
        return self.get("DITING_LEVEL", "L1")

    @property
    def ai_model(self) -> str:
        return self.get("AI_MODEL", "deepseek/deepseek-v4-pro")

    @property
    def ai_api_key(self) -> str:
        return self.get("AI_API_KEY", "")

    @property
    def mx_apikey(self) -> str:
        return self.get("MX_APIKEY", "")

    @property
    def notify_default(self) -> str:
        return self.get("NOTIFY_DEFAULT", "local")

    # ── watchlist 加载与验证 ──────────────────────

    def load_watchlist(
        self, path: str | None = None, validate: bool = True
    ) -> list[dict[str, Any]]:
        """加载自选股 CSV，可选验证。

        Args:
            path: CSV 文件路径，默认为 config/watchlist.csv
            validate: 是否验证每一行的代码格式和市场字段

        Returns:
            [{"code": "002475", "name": "立讯精密", "market": "sz"}, ...]

        Raises:
            ConfigError: 文件不存在或验证失败
        """
        filepath = Path(path) if path else self._root / "config" / "watchlist.csv"
        if not filepath.exists():
            raise ConfigError(f"watchlist file not found: {filepath}")

        rows: list[dict[str, Any]] = []
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, start=1):
                rows.append(row)

        if not rows:
            logger.warning("config.watchlist.empty", path=str(filepath))
            return []

        if validate:
            self._validate_watchlist(rows, str(filepath))

        # 去重
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for row in rows:
            code = row.get("code", "").strip()
            if code and code not in seen:
                seen.add(code)
                unique.append(row)

        if len(unique) < len(rows):
            logger.info(
                "config.watchlist.deduped",
                original=len(rows),
                unique=len(unique),
            )

        return unique

    @classmethod
    def _validate_watchlist(cls, rows: list[dict[str, Any]], path: str) -> None:
        """验证自选股 CSV 内容。

        Raises:
            ConfigError: 格式错误或验证失败
        """
        errors: list[str] = []

        for i, row in enumerate(rows, start=2):  # 第1行是header
            # 去掉空白
            cleaned = {k.strip(): v.strip() if isinstance(v, str) else v
                       for k, v in row.items()}

            # 必填列
            for col in cls.WATCHLIST_REQUIRED_COLS:
                if col not in cleaned or not cleaned[col]:
                    errors.append(
                        f"行{i}: 缺少必填列 '{col}'"
                    )

            code = cleaned.get("code", "")
            market = cleaned.get("market", "").lower()

            # 代码格式：6位数字
            if code and not cls._CODE_PATTERN.match(code):
                errors.append(
                    f"行{i}: 代码 '{code}' 格式错误，应为6位数字"
                )

            # 市场字段：sz/sh/bj
            if market and not cls._MARKET_PATTERN.match(market):
                errors.append(
                    f"行{i}: 市场 '{market}' 无效，应为 sz/sh/bj"
                )

        if errors:
            raise ConfigError(
                f"watchlist 验证失败 ({path}):\n" + "\n".join(errors)
            )
