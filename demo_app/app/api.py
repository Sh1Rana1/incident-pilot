"""模拟 POST /users 的 API 入口。"""

import sqlite3

from demo_app.app.service import create_user


def post_users(payload: dict, connection: sqlite3.Connection) -> dict:
    # BUG-001：没有根据 API 文档检查 user_id 和 email。
    create_user(payload, connection)
    return {"status": 201}
