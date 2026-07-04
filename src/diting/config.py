"""谛听 · 配置管理"""

import csv
import os
from pathlib import Path
from typing import Any


class Config:
    """应用配置，从 .env 和 watchlist.csv 加载"""

    def __init__(self, project_root: Path | None = None):
        self._root = project_root or Path.cwd()
        self._data: dict[str, str] = {}
        self._load_env()

    def _load_env(self) -> None:
        """加载 .env 文件（不覆盖已有的环境变量）"""
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
        """获取配置值（优先级：环境变量 > .env > default）"""
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

    def load_watchlist(self, path: str | None = None) -> list[dict[str, Any]]:
        """加载自选股 CSV"""
        filepath = Path(path) if path else self._root / "config" / "watchlist.csv"
        if not filepath.exists():
            return []
        with open(filepath, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
