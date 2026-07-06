"""谛听 · 邮件推送（桩实现）

当前为桩实现，实际邮件集成留在后续版本完成。
"""

from __future__ import annotations

from ..infra.logging_config import get_logger
from .base import Notifier

logger = get_logger(__name__)


class EmailNotifier(Notifier):
    """邮件推送（桩实现）。"""

    channel_name = "email"

    def send(self, message: str) -> bool:
        """桩实现：记录日志，假装发送邮件。

        Args:
            message: 邮件内容

        Returns:
            True
        """
        snippet = message[:100] + "..." if len(message) > 100 else message
        logger.info("email.stub", msg=f"假装发送邮件: {snippet}")
        return True
