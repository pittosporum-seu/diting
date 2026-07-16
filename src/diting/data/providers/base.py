"""谛听 · 数据提供者抽象基类

所有数据源必须实现此接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ...schema import FundFlow, HistoricalData, RealtimeQuote


class DataProvider(ABC):
    """数据提供者抽象基类。

    定义了所有数据源必须实现的接口。具体实现（mx-data, akshare, SQLite）
    各自决定如何获取数据，上层通过此接口统一调用。
    """

    # ── 必须实现的属性 ──────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源唯一标识，如 'mx_data', 'akshare'"""
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级，数字越小优先级越高。Repository 按此排序降级链"""
        ...

    # ── 必须实现的方法 ──────────────────────────────

    @abstractmethod
    def health_check(self) -> bool:
        """检查数据源是否可用。

        Returns:
            True 表示可用，False 表示不可用。
            实现应快速返回（<1s），不阻塞调用方。
        """
        ...

    @abstractmethod
    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        """获取实时行情。

        Args:
            symbols: 股票代码列表，如 ['002475', '603659']

        Returns:
            {symbol: RealtimeQuote} 字典

        Raises:
            DataUnavailableError: 数据源不可用
        """
        ...

    @abstractmethod
    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        """获取历史日线行情。

        Args:
            symbol: 股票代码
            start: 起始日期
            end: 结束日期

        Returns:
            HistoricalData 包含 DataFrame + 元信息

        Raises:
            DataUnavailableError: 数据源不可用
        """
        ...

    # ── 可选方法（子类按需覆写）──────────────────────

    def fetch_financials(self, symbol: str) -> dict:
        """获取财务数据（可选）。

        Raises:
            NotImplementedError: 该数据源不支持财务数据
        """
        raise NotImplementedError(
            f"{self.name} does not support financials"
        )

    def fetch_fund_flow(self, symbol: str, day: date) -> FundFlow:
        """获取资金流向（可选）。

        Raises:
            NotImplementedError: 该数据源不支持资金流向
        """
        raise NotImplementedError(
            f"{self.name} does not support fund flow"
        )

    def fetch_minute(self, symbol: str, day: date) -> HistoricalData:
        """获取分钟级数据（可选）。

        Raises:
            NotImplementedError: 该数据源不支持分钟数据
        """
        raise NotImplementedError(
            f"{self.name} does not support minute data"
        )

    @classmethod
    def from_config(cls, name: str, settings: dict | None = None):
        """根据名称和配置创建 provider 实例。

        Args:
            name: provider 名称，如 'eltdx', 'mx_data', 'akshare', 'ashare'。
            settings: 可选的初始化参数字典。

        Returns:
            DataProvider 实例。

        Raises:
            ValueError: 未知的 provider 名称。
        """
        mapping = {
            "eltdx": "diting.data.providers.eltdx.ELtdxProvider",
            "ashare": "diting.data.providers.ashare.AshareProvider",
            "east_money": "diting.data.providers.east_money.EastMoneyProvider",
            "mx_data": "diting.data.providers.mx_data.MxDataProvider",
            "akshare": "diting.data.providers.akshare.AkShareProvider",
        }
        class_path = mapping.get(name)
        if class_path is None:
            raise ValueError(f"Unknown provider: {name}")

        mod_path, _, cls_name = class_path.rpartition(".")
        import importlib
        mod = importlib.import_module(mod_path)
        provider_cls = getattr(mod, cls_name)

        if settings:
            provider = provider_cls()
            for k, v in settings.items():
                if hasattr(provider, k):
                    setattr(provider, k, v)
            return provider
        return provider_cls()
