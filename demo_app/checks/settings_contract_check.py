"""按需验证环境变量迁移契约。"""

import unittest

from demo_app.app.settings import load_request_timeout


class SettingsContractTests(unittest.TestCase):
    def test_current_timeout_variable_is_loaded(self):
        self.assertEqual(
            load_request_timeout({"HTTP_TIMEOUT_SECONDS": "15"}),
            15,
        )

    def test_legacy_variable_is_not_silently_used(self):
        with self.assertRaisesRegex(KeyError, "HTTP_TIMEOUT_SECONDS"):
            load_request_timeout({"REQUEST_TIMEOUT_SECONDS": "15"})

    def test_non_positive_timeout_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            load_request_timeout({"HTTP_TIMEOUT_SECONDS": "0"})
