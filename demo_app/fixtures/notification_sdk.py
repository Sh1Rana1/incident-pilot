"""模拟不可检查源码的 Notification SDK v3。"""


class NotificationSDK:
    def send(self, *, recipient: str, content: str) -> str:
        if not recipient or not content:
            raise ValueError("recipient and content are required")
        return "notification-001"
