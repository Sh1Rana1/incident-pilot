"""Webhook 客户端配置。供应商约束由外部契约定义。"""

from demo_app.fixtures.provider_gateway import validate_timeout


WEBHOOK_TIMEOUT_SECONDS = 30


def deliver_webhook() -> None:
    validate_timeout(WEBHOOK_TIMEOUT_SECONDS)
