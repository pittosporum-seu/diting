"""谛听 · A股多模型 AI 投资分析工具。"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("diting")
except PackageNotFoundError:  # pragma: no cover - only a raw, uninstalled source tree
    __version__ = "0+unknown"
