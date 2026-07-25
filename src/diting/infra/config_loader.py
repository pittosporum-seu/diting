"""谛听 · YAML 配置加载器

惰性加载 config/diting.yaml，模块级缓存。
文件不存在时返回空 dict，完全向后兼容。
"""

from __future__ import annotations

from pathlib import Path

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
        """加载 diting.yaml（惰性，缓存结果）。

        Args:
            root: 项目根目录，默认为当前工作目录。

        Returns:
            完整配置字典，文件不存在时返回 {}。
        """
        if cls._config is not None:
            return cls._config
        path = (root or Path.cwd()) / "config" / "diting.yaml"
        if not path.exists():
            cls._config = {}
            return cls._config
        with open(path, encoding="utf-8") as f:
            cls._config = yaml.safe_load(f) or {}
        return cls._config

    @classmethod
    def get_section(cls, section: str, root: Path | None = None) -> dict:
        """获取某个配置段落。

        Args:
            section: 段落名，如 'providers', 'engines'。
            root: 项目根目录，默认为当前工作目录。

        Returns:
            段落字典，不存在时返回 {}。
        """
        return cls.get(root).get(section, {})

    @classmethod
    def reset(cls) -> None:
        """重置缓存（测试用）。"""
        cls._config = None
