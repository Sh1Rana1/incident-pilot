"""Demo App 故障夹具测试：通过代表三个故障仍能被稳定复现。"""

import sqlite3
import json
import shutil
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from demo_app.app.api import post_users
from demo_app.app.database import create_connection
from demo_app.app.pool import ConnectionPool
from demo_app.app.worker import process_job
from demo_app.app.webhook import deliver_webhook


ROOT = Path(__file__).resolve().parent
NEW_CASES = {
    "async_missing_await": (
        "TypeError: 'coroutine' object is not subscriptable",
        "async_profile_contract", "demo_app/app/async_jobs.py",
        "profile = fetch_profile(user_id)",
        "profile = await fetch_profile(user_id)",
    ),
    "retry_non_idempotent": (
        "RuntimeError: duplicate charge: expected 1, got 2",
        "payment_single_charge_contract", "demo_app/app/retry_policy.py",
        "gateway.charge(order_id, amount)",
        "gateway.charge(order_id, amount, idempotency_key=order_id)",
    ),
}


class ExpandedBenchmarkTests(unittest.TestCase):
    def test_new_entrypoints_reproduce_expected_failures(self):
        for case_id, (error, *_) in NEW_CASES.items():
            for entry in (["-m", "demo_app.run_case"], ["demo_app/run_case.py"]):
                with self.subTest(case=case_id, entry=entry):
                    result = subprocess.run(
                        [sys.executable, *entry, case_id], cwd=ROOT,
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(error, result.stderr)

    def test_harness_distinguishes_reproduction_from_contract_failure(self):
        import harness
        from registry import registry
        from models import ToolResult
        for case_id, (_, contract, *_) in NEW_CASES.items():
            for check_id, expected in (("demo_" + case_id, True), (contract, False)):
                with self.subTest(check=check_id):
                    result = ToolResult.model_validate_json(registry.execute(
                        "run_check", json.dumps({"check_id": check_id}),
                    ))
                    self.assertTrue(result.ok, result.error)
                    self.assertEqual(result.data["expectation_met"], expected)

    def test_reference_fixes_pass_in_temporary_copy_only(self):
        import harness
        manifest, _ = harness.load_harness_manifest()
        for case_id, (_, contract, relative, before, after) in NEW_CASES.items():
            with self.subTest(case=case_id), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(ROOT / "demo_app", root / "demo_app",
                                ignore=shutil.ignore_patterns("__pycache__"))
                original = (ROOT / relative).read_bytes()
                target = root / relative
                content = target.read_text(encoding="utf-8")
                self.assertEqual(content.count(before), 1)
                target.write_text(content.replace(before, after), encoding="utf-8")
                check = next(item for item in manifest.checks if item.check_id == contract)
                for args in (["-m", "demo_app.run_case", case_id],
                             ["-m", "unittest", "-q", check.target]):
                    result = subprocess.run([sys.executable, *args], cwd=root,
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((ROOT / relative).read_bytes(), original)

    def test_new_evaluation_assets_exist_and_load_without_schema_changes(self):
        from evaluation import load_cases
        cases = load_cases(ROOT / "demo_app/evals", set(NEW_CASES))
        self.assertEqual({case.case_id for case in cases}, set(NEW_CASES))
        for case in cases:
            for relative in [*case.evidence_files, *case.relevant_docs,
                             f"demo_app/logs/{case.case_id}.log"]:
                self.assertTrue((ROOT / relative).is_file(), relative)
            self.assertIn(NEW_CASES[case.case_id][0],
                          (ROOT / f"demo_app/logs/{case.case_id}.log").read_text())

    def test_internal_assets_blocked_for_read_search_and_list(self):
        from tools import (read_file, search_code, list_files,
                           ReadFileArgs, SearchCodeArgs, ListFilesArgs)
        protected = [
            "demo_app/checks/async_contract_check.py",
            "demo_app/checks/payment_contract_check.py",
            "demo_app/fixtures/payment_gateway.py",
            "demo_app/evals/async_missing_await.json",
            "demo_app/evals/retry_non_idempotent.json",
            "test_demo_app.py",
        ]
        for relative in protected:
            self.assertFalse(read_file(ReadFileArgs(path=relative)).ok, relative)
        for query in ("root_cause_keywords", "test_profile_name_is_resolved",
                      "self.receipts", "NEW_CASES"):
            result = search_code(SearchCodeArgs(query=query))
            self.assertTrue(result.ok)
            self.assertFalse(set(protected) & {m["path"] for m in result.data["matches"]})
        for path in ("demo_app", "demo_app/checks", "demo_app/fixtures", "demo_app/evals"):
            result = list_files(ListFilesArgs(path=path, max_depth=5))
            self.assertTrue(result.ok)
            self.assertFalse(set(protected) & {e["path"] for e in result.data["entries"]})

    def test_new_business_code_remains_readable(self):
        from tools import read_file, ReadFileArgs
        for _, _, relative, *_ in NEW_CASES.values():
            self.assertTrue(read_file(ReadFileArgs(path=relative)).ok)


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
