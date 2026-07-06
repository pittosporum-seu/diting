"""谛听 · 本地文件保存通知器"""

from __future__ import annotations

import os
from datetime import datetime

from ..infra.logging_config import get_logger
from .base import Notifier

logger = get_logger(__name__)


class LocalNotifier(Notifier):
    """将 HTML 报告保存到本地 output/ 目录。"""

    channel_name = "local"

    def __init__(self, output_dir: str = "output") -> None:
        self._output_dir = output_dir

    def send(self, message: str) -> bool:
        """保存报告到本地文件。

        Args:
            message: HTML 报告内容

        Returns:
            True 表示保存成功
        """
        os.makedirs(self._output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self._output_dir, f"report_{ts}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(message)
        logger.info("local.saved", path=path)
        return True
