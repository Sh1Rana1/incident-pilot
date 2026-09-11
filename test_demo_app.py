"""Demo App 故障夹具测试：通过代表三个故障仍能被稳定复现。"""

import sqlite3
import unittest

from demo_app.app.api import post_users
from demo_app.app.database import create_connection
from demo_app.app.pool import ConnectionPool
from demo_app.app.worker import process_job


class DemoIncidentTests(unittest.TestCase):
    def test_missing_user_id_reproduces_key_error(self) -> None:
        connection = create_connection()
        try:
            with self.assertRaisesRegex(KeyError, "user_id"):
                post_users({"email": "demo@example.com"}, connection)
        finally:
            connection.close()

    def test_schema_mismatch_reproduces_database_error(self) -> None:
        connection = create_connection()
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "no column named user_id"):
                post_users(
                    {"user_id": "user-001", "email": "demo@example.com"},
                    connection,
                )
        finally:
            connection.close()

    def test_connection_leak_exhausts_pool(self) -> None:
        pool = ConnectionPool(max_size=2)
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "invalid job payload"):
                process_job(pool, should_fail=True)
        with self.assertRaisesRegex(RuntimeError, "connection pool exhausted"):
            process_job(pool, should_fail=False)
        self.assertEqual(pool.active, 2)


if __name__ == "__main__":
    unittest.main()
