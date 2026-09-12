"""Demo App 故障夹具测试：通过代表三个故障仍能被稳定复现。"""

import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from demo_app.app.api import post_users
from demo_app.app.database import create_connection
from demo_app.app.pool import ConnectionPool
from demo_app.app.worker import process_job
from demo_app.app.webhook import deliver_webhook


class DemoIncidentTests(unittest.TestCase):
    def test_direct_script_launch_can_import_demo_app(self) -> None:
        root = Path(__file__).resolve().parent
        completed = subprocess.run(
            [sys.executable, str(root / "demo_app" / "run_case.py"), "missing_user_id"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("KeyError", output)
        self.assertNotIn("ModuleNotFoundError", output)

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

    def test_documentation_required_reproduces_provider_rejection(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "timeout_policy_violation"):
            deliver_webhook()


if __name__ == "__main__":
    unittest.main()
