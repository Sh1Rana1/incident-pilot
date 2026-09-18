"""用户资料缓存的最小读写实现。"""


def seed_profile_cache(user_id: str) -> dict[str, dict]:
    return {
        f"profile:v2:{user_id}": {
            "user_id": user_id,
            "display_name": "Demo User",
        }
    }


def load_profile_cache(cache: dict[str, dict], user_id: str) -> dict:
    key = f"profile:{user_id}"
    try:
        return cache[key]
    except KeyError as exc:
        raise KeyError(f"cache miss: {key}") from exc
