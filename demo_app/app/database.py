"""创建已经完成 external_id 迁移的 SQLite 数据库。"""

import sqlite3


def create_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, external_id TEXT UNIQUE, email TEXT NOT NULL)"
    )
    return connection
