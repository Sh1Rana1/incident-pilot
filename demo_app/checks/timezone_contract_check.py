"""按需验证跨时区 SLA 计算契约。"""

import unittest

from demo_app.app.time_window import completed_within_sla


class TimezoneContractTests(unittest.TestCase):
    def test_equivalent_offsets_use_elapsed_time(self):
        self.assertTrue(completed_within_sla(
            "2026-09-18T00:00:00Z",
            "2026-09-18T08:45:00+08:00",
            max_minutes=60,
        ))

    def test_elapsed_time_outside_sla_is_rejected(self):
        self.assertFalse(completed_within_sla(
            "2026-09-18T00:00:00Z",
            "2026-09-18T09:15:00+08:00",
            max_minutes=60,
        ))
