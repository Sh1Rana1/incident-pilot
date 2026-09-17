"""Demo App 故障夹具测试：通过代表十二个故障仍能被稳定复现。"""

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
from demo_app.run_case import run_case


class DemoIncidentTests(unittest.TestCase):
    EXPANDED_CASES = (
        ("async_missing_await", TypeError, "coroutine.*not subscriptable"),
        ("retry_non_idempotent", RuntimeError, "duplicate charge"),
        ("timezone_mismatch", TypeError, "offset-naive.*offset-aware"),
        ("cache_key_version", KeyError, "profile:v1:user-001"),
        ("pagination_off_by_one", RuntimeError, "expected 6, got 4"),
        ("config_env_rename", RuntimeError, "loaded 5000, expected 1200"),
        (
            "transaction_rollback",
            sqlite3.OperationalError,
            "within a transaction",
        ),
        (
            "dependency_contract_change",
            TypeError,
            "unexpected keyword argument 'to'",
        ),
    )

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

    def test_expanded_cases_reproduce_expected_failures(self) -> None:
        for case_id, exception_type, message in self.EXPANDED_CASES:
            with self.subTest(case_id=case_id):
                with self.assertRaisesRegex(exception_type, message):
                    run_case(case_id)

    def test_public_source_does_not_contain_explicit_bug_labels(self) -> None:
        root = Path(__file__).resolve().parent / "demo_app" / "app"
        contents = "\n".join(
            path.read_text(encoding="utf-8") for path in root.glob("*.py")
        )
        self.assertNotIn("BUG-", contents)


if __name__ == "__main__":
    unittest.main()
