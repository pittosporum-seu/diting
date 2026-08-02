"""谛听 · A股多模型 AI 投资分析工具。"""

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

try:
    __version__ = version("diting")
except PackageNotFoundError:  # pragma: no cover - only a raw, uninstalled source tree
    __version__ = "0+unknown"

from .enums import AnalysisProfile, FetchMode
from .schema import AnalysisRun, DataResult, RealtimeQuote, ScanResult

if TYPE_CHECKING:
    from .facade import Diting

__all__ = [
    "AnalysisProfile",
    "AnalysisRun",
    "DataResult",
    "Diting",
    "FetchMode",
    "RealtimeQuote",
    "ScanResult",
    "__version__",
]


def __getattr__(name: str) -> Any:
    """Load the runtime facade only when requested, keeping core imports lightweight."""

    if name == "Diting":
        from .facade import Diting

        return Diting
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
