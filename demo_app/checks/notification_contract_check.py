"""按需验证 Notification SDK v3 适配契约。"""

import unittest

from demo_app.app.notification_client import send_welcome_notification
from demo_app.fixtures.notification_sdk import NotificationSDK


class NotificationContractTests(unittest.TestCase):
    def test_welcome_notification_uses_current_sdk_contract(self):
        self.assertEqual(
            send_welcome_notification(
                NotificationSDK(),
                recipient="user@example.com",
                message="Welcome",
            ),
            "notification-001",
        )
