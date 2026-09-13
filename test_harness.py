"""V11 安全测试 Harness 测试；不调用模型 API。"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import harness
import runtime_tools
from models import ToolResult
from provenance import build_observation
from registry import registry


def call_harness(name: str, arguments: dict) -> ToolResult:
    return ToolResult.model_validate_json(
        registry.execute(name, json.dumps(arguments))
    )


def unittest_manifest() -> harness.HarnessManifest:
    return harness.HarnessManifest.model_validate({
        "version": 1,
        "checks": [{
            "check_id": "unit_safe",
            "runner": "unittest",
            "target": "demo_app.checks.test_smoke",
            "description": "safe unit test",
            "timeout_seconds": 30,
            "expected_exit_codes": [0],
        }],
    })


class HarnessTests(unittest.TestCase):
    def test_list_checks_does_not_expose_target_or_command(self) -> None:
        result = call_harness("list_checks", {})

        self.assertTrue(result.ok)
        self.assertGreaterEqual(len(result.data["checks"]), 5)
        first = result.data["checks"][0]
        self.assertIn("check_id", first)
        self.assertNotIn("target", first)
        self.assertNotIn("argv", first)
        self.assertNotIn("command", first)

    def test_run_check_schema_rejects_model_supplied_execution_fields(self) -> None:
        result = call_harness("run_check", {
            "check_id": "demo_missing_user_id",
            "command": "whoami",
            "path": "../outside",
        })

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "工具参数校验失败")

    @patch("harness.subprocess.run")
    def test_unknown_check_is_rejected_before_process_start(self, run_mock) -> None:
        result = call_harness("run_check", {"check_id": "not_registered"})

        self.assertFalse(result.ok)
        self.assertEqual(result.meta["reason"], "harness_check_not_registered")
        run_mock.assert_not_called()

    @patch("harness.subprocess.run")
    def test_unittest_runner_uses_fixed_argv_minimal_env_and_structured_counts(
        self, run_mock
    ) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout="",
            stderr=(
                "FAIL: test_one (tests.Sample)\n"
                "ERROR: test_two (tests.Sample)\n"
                "Ran 5 tests in 0.01s\nFAILED (failures=1, errors=1)\n"
            ),
        )
        with patch(
            "harness.load_harness_manifest",
            return_value=(unittest_manifest(), "manifest-digest"),
        ), patch.dict(os.environ, {"API_KEY": "never-inherit"}):
            timeout_token = runtime_tools.activate_runtime_timeout(12)
            try:
                result = call_harness("run_check", {"check_id": "unit_safe"})
            finally:
                runtime_tools.reset_runtime_timeout(timeout_token)

        self.assertTrue(result.ok)
        self.assertEqual(result.data["passed_count"], 3)
        self.assertEqual(result.data["failed_count"], 2)
        self.assertEqual(result.data["failed_tests"], ["test_one", "test_two"])
        self.assertEqual(result.data["timeout_seconds"], 12)
        self.assertFalse(result.data["expectation_met"])
        called_argv = run_mock.call_args.args[0]
        self.assertEqual(
            called_argv[1:],
            ["-m", "unittest", "-q", "demo_app.checks.test_smoke"],
        )
        self.assertFalse(run_mock.call_args.kwargs["shell"])
        self.assertNotIn("API_KEY", run_mock.call_args.kwargs["env"])

    @patch("harness.subprocess.run")
    def test_timeout_is_structured_and_uses_lower_hard_limit(self, run_mock) -> None:
        run_mock.side_effect = subprocess.TimeoutExpired(
            cmd=["python"], timeout=4, output="partial", stderr="slow"
        )
        with patch(
            "harness.load_harness_manifest",
            return_value=(unittest_manifest(), "manifest-digest"),
        ):
            timeout_token = runtime_tools.activate_runtime_timeout(4)
            try:
                result = call_harness("run_check", {"check_id": "unit_safe"})
            finally:
                runtime_tools.reset_runtime_timeout(timeout_token)

        self.assertFalse(result.ok)
        self.assertTrue(result.meta["timed_out"])
        self.assertEqual(result.meta["timeout_seconds"], 4)

    @patch("harness.subprocess.run")
    def test_completed_check_is_replayed_from_shared_ledger(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=0, stdout="", stderr="Ran 1 test\nOK"
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "harness.load_harness_manifest",
            return_value=(unittest_manifest(), "manifest-digest"),
        ):
            database = str(Path(directory) / "state.sqlite3")
            first_token = runtime_tools.activate_runtime_execution(
                "harness-exec", database
            )
            try:
                first = call_harness("run_check", {"check_id": "unit_safe"})
            finally:
                runtime_tools.reset_runtime_execution(first_token)
            second_token = runtime_tools.activate_runtime_execution(
                "harness-exec", database
            )
            try:
                second = call_harness("run_check", {"check_id": "unit_safe"})
            finally:
                runtime_tools.reset_runtime_execution(second_token)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(run_mock.call_count, 1)
        self.assertFalse(first.meta["replayed"])
        self.assertTrue(second.meta["replayed"])
        self.assertEqual(first.data["run_id"], second.data["run_id"])

    def test_manifest_rejects_duplicate_ids_and_unsafe_targets(self) -> None:
        duplicate = {
            "version": 1,
            "checks": [
                unittest_manifest().checks[0].model_dump(),
                unittest_manifest().checks[0].model_dump(),
            ],
        }
        with self.assertRaises(ValueError):
            harness.HarnessManifest.model_validate(duplicate)
        with self.assertRaises(ValueError):
            harness.HarnessCheck.model_validate({
                **unittest_manifest().checks[0].model_dump(),
                "target": "test_demo_app --buffer && whoami",
            })
        with self.assertRaises(ValueError):
            harness.HarnessCheck.model_validate({
                **unittest_manifest().checks[0].model_dump(),
                "target": "test_harness.HarnessTests",
            })

    def test_run_check_creates_grounded_runtime_observation(self) -> None:
        result = call_harness("run_check", {"check_id": "demo_missing_user_id"})
        observation, _ = build_observation(
            "obs-harness",
            "call-harness",
            1,
            "run_check",
            '{"check_id":"demo_missing_user_id"}',
            result.model_dump_json(),
            1,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.data["expectation_met"])
        self.assertEqual(result.data["exception_type"], "KeyError")
        self.assertEqual(observation.sources[0].source_type, "runtime")
        self.assertEqual(observation.sources[0].runtime_id, result.data["run_id"])


if __name__ == "__main__":
    unittest.main()
