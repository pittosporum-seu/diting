"""谛听 · 飞书推送（桩实现）

当前为桩实现，实际飞书集成留在后续版本完成。
"""

from __future__ import annotations

from ..infra.logging_config import get_logger
from .base import Notifier

logger = get_logger(__name__)


class FeishuNotifier(Notifier):
    """飞书机器人推送（桩实现）。"""

    channel_name = "feishu"

    def send(self, message: str) -> bool:
        """桩实现：记录日志，假装发送到飞书。

        Args:
            message: 推送内容

        Returns:
            True
        """
        snippet = message[:100] + "..." if len(message) > 100 else message
        logger.info("feishu.stub", msg=f"假装发送到飞书: {snippet}")
        return True
