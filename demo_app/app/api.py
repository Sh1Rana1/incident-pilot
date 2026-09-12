"""模拟 POST /users 的 API 入口。"""

import sqlite3

from demo_app.app.service import create_user


def post_users(payload: dict, connection: sqlite3.Connection) -> dict:
    create_user(payload, connection)
    return {"status": 201}
