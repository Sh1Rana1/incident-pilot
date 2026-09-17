"""批量导入记录时维护数据库事务。"""

import sqlite3


def create_import_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE imports (id TEXT PRIMARY KEY)")
    connection.commit()
    return connection


def import_then_continue(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN")
        connection.execute("INSERT INTO imports (id) VALUES ('batch-1')")
        raise ValueError("invalid row")
    except ValueError:
        pass
    connection.execute("BEGIN")
