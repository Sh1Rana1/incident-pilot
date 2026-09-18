"""按需验证缓存 Key 版本契约。"""

import unittest

from demo_app.app.cache_store import load_profile_cache, seed_profile_cache


class CacheContractTests(unittest.TestCase):
    def test_seeded_profile_can_be_loaded(self):
        cache = seed_profile_cache("user-001")
        self.assertEqual(
            load_profile_cache(cache, "user-001")["display_name"],
            "Demo User",
        )

    def test_user_keys_remain_independent(self):
        cache = seed_profile_cache("user-001")
        cache.update(seed_profile_cache("user-002"))
        self.assertEqual(load_profile_cache(cache, "user-002")["user_id"], "user-002")
