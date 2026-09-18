"""批量导入事务的最小实现。"""

import sqlite3


def create_import_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE imported_users (user_id TEXT PRIMARY KEY, status TEXT NOT NULL)"
    )
    return connection


def import_then_continue(connection: sqlite3.Connection) -> int:
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO imported_users (user_id, status) VALUES (?, ?)",
        ("user-001", "pending"),
    )
    try:
        raise ValueError("invalid import row after first insert")
    except ValueError:
        connection.commit()
    return connection.execute("SELECT COUNT(*) FROM imported_users").fetchone()[0]
