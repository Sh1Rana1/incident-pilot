"""按需执行的业务契约检查，不纳入默认 discovery。"""

import asyncio
import unittest

from demo_app.app.async_jobs import profile_name


class AsyncContractTests(unittest.TestCase):
    def test_profile_name_is_resolved(self):
        self.assertEqual(asyncio.run(profile_name("user-001")), "Demo User")
