"""POST /users 的公开行为契约；供 V13 隔离补丁验证使用。"""

import unittest
from unittest.mock import Mock, patch

from demo_app.app.api import post_users


class ApiContractTests(unittest.TestCase):
    @patch("demo_app.app.api.create_user")
    def test_missing_user_id_returns_400_without_calling_service(
        self,
        create_user: Mock,
    ) -> None:
        result = post_users({"email": "demo@example.com"}, Mock())

        self.assertEqual(result["status"], 400)
        self.assertIn("user_id", result["error"])
        create_user.assert_not_called()

    @patch("demo_app.app.api.create_user")
    def test_missing_email_returns_400_without_calling_service(
        self,
        create_user: Mock,
    ) -> None:
        result = post_users({"user_id": "user-001"}, Mock())

        self.assertEqual(result["status"], 400)
        self.assertIn("email", result["error"])
        create_user.assert_not_called()

    @patch("demo_app.app.api.create_user")
    def test_complete_payload_still_returns_201(self, create_user: Mock) -> None:
        connection = Mock()

        result = post_users(
            {"user_id": "user-001", "email": "demo@example.com"},
            connection,
        )

        self.assertEqual(result, {"status": 201})
        create_user.assert_called_once_with(
            {"user_id": "user-001", "email": "demo@example.com"},
            connection,
        )


if __name__ == "__main__":
    unittest.main()
