"""用户服务层。"""

import sqlite3

from demo_app.app.repository import insert_user


def create_user(payload: dict, connection: sqlite3.Connection) -> None:
    # BUG-001：默认 API 层已经校验，但 api.py 实际没有校验。
    user_id = payload["user_id"]
    email = payload["email"]
    insert_user(connection, user_id, email)
