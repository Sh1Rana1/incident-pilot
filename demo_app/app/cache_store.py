"""用户资料缓存的写入与读取。"""


def seed_profile_cache(user_id: str) -> dict[str, dict]:
    return {f"profile:v2:{user_id}": {"name": "Ada"}}


def read_profile(cache: dict[str, dict], user_id: str) -> dict:
    return cache[f"profile:v1:{user_id}"]
