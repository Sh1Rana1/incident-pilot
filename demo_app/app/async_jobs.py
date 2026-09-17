"""异步资料查询入口。"""


async def fetch_profile(user_id: str) -> dict:
    return {"user_id": user_id, "display_name": "Demo User"}


async def profile_name(user_id: str) -> str:
    profile = fetch_profile(user_id)
    return profile["display_name"]
