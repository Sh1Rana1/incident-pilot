"""用户数据访问层。这里故意保留了迁移前的旧字段名。"""

import sqlite3


def insert_user(connection: sqlite3.Connection, user_id: str, email: str) -> None:
    # BUG-002：数据库已经改名为 external_id，这里仍然写入 user_id。
    connection.execute(
        "INSERT INTO users (user_id, email) VALUES (?, ?)",
        (user_id, email),
    )
    connection.commit()
