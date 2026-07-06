"""谛听 · 推送通知抽象基类"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    """推送通知器抽象基类。

    所有通知渠道（飞书、邮件、本地文件）需实现此接口。
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """通知渠道唯一标识，如 'feishu', 'email', 'local'"""
        ...

    @abstractmethod
    def send(self, message: str) -> bool:
        """发送通知。

        Args:
            message: 通知内容（HTML 报告或纯文本摘要）

        Returns:
            True 表示发送成功
        """
        ...

    def health_check(self) -> bool:
        """健康检查，默认返回 True。子类可覆写以实现实际连通性测试。"""
        return True
