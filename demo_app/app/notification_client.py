"""通知服务适配器。"""

from demo_app.fixtures.notification_sdk import send_message


def notify_user(user_id: str) -> None:
    send_message(to=user_id, message="job completed")
