"""按需验证公开事件接口的分页契约。"""

import unittest

from demo_app.app.pagination import paginate_events


class PaginationContractTests(unittest.TestCase):
    def test_first_page_starts_with_first_event(self):
        events = ["event-001", "event-002", "event-003"]
        self.assertEqual(
            paginate_events(events, page=1, page_size=2),
            ["event-001", "event-002"],
        )

    def test_second_page_contains_remaining_event(self):
        events = ["event-001", "event-002", "event-003"]
        self.assertEqual(paginate_events(events, page=2, page_size=2), ["event-003"])

    def test_page_zero_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "page must be at least 1"):
            paginate_events(["event-001"], page=0, page_size=1)
