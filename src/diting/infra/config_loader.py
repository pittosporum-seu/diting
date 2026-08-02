"""Compatibility access to an already validated configuration snapshot."""

from __future__ import annotations

from typing import Any

from ..config import AppConfig


class ConfigLoader:
    """Expose validated sections while legacy consumers migrate to injection.

    This class never reads files or environment variables. The composition root must call
    :meth:`configure` with the immutable snapshot produced by ``load_app_config``.
    """

    _settings: AppConfig = AppConfig()

    @classmethod
    def configure(cls, settings: AppConfig) -> None:
        cls._settings = settings

    @classmethod
    def current(cls) -> AppConfig:
        return cls._settings

    @classmethod
    def get(cls, root=None) -> dict[str, Any]:
        del root
        return cls._settings.model_dump(mode="python")

    @classmethod
    def get_section(cls, section: str, root=None) -> Any:
        del root
        value = getattr(cls._settings, section, None)
        if value is None:
            return {}
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="python")
        if isinstance(value, tuple):
            return [
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in value
            ]
        return value

    @classmethod
    def reset(cls) -> None:
        cls._settings = AppConfig()
