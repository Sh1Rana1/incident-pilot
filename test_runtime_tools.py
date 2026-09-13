"""V10 受限 Runtime 与持久幂等账本测试；不调用模型 API。"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_tools
from models import ToolResult
from provenance import build_observation
from registry import registry


def call_runtime(arguments: dict) -> ToolResult:
    return ToolResult.model_validate_json(
        registry.execute("run_demo_case", json.dumps(arguments))
    )


class RuntimeToolTests(unittest.TestCase):
    def test_allowlisted_case_is_reproduced_without_shell(self) -> None:
        result = call_runtime({"case_id": "missing_user_id"})

        self.assertTrue(result.ok)
        self.assertNotEqual(result.data["exit_code"], 0)
        self.assertEqual(result.data["exception_type"], "KeyError")
        self.assertIn("KeyError", result.data["exception_message"])
        self.assertTrue(any(
            frame["file"] == "demo_app/app/service.py"
            for frame in result.data["traceback_frames"]
        ))
        self.assertTrue(result.data["run_id"].startswith("runtime-missing_user_id-"))
        self.assertEqual(result.data["argv"][0], "<current-python>")
        self.assertNotIn(str(runtime_tools.ROOT), result.data["stderr_excerpt"])
        observation, _ = build_observation(
            "obs-runtime", "call-runtime", 1, "run_demo_case",
            '{"case_id":"missing_user_id"}', result.model_dump_json(), 1,
        )
        self.assertIn("KeyError", observation.result_excerpt)
        self.assertIn("demo_app/app/service.py", observation.result_excerpt)

    def test_arbitrary_command_or_unknown_case_is_rejected_by_schema(self) -> None:
        result = call_runtime({"case_id": "missing_user_id", "command": "whoami"})
        unknown = call_runtime({"case_id": "not_registered"})

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "工具参数校验失败")
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.error, "工具参数校验失败")

    @patch("runtime_tools.subprocess.run")
    def test_timeout_is_returned_as_structured_failure(self, run_mock) -> None:
        run_mock.side_effect = subprocess.TimeoutExpired(
            cmd=["python"], timeout=1, output="partial", stderr="slow"
        )
        token = runtime_tools.activate_runtime_timeout(1)
        try:
            result = call_runtime({"case_id": "schema_mismatch"})
        finally:
            runtime_tools.reset_runtime_timeout(token)

        self.assertFalse(result.ok)
        self.assertTrue(result.meta["timed_out"])
        self.assertEqual(result.meta["timeout_seconds"], 1)

    @patch("runtime_tools.subprocess.run")
    def test_child_environment_does_not_inherit_api_key(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=1, stdout="", stderr="RuntimeError: demo"
        )
        with patch.dict(os.environ, {"API_KEY": "must-not-leak"}):
            result = call_runtime({"case_id": "documentation_required"})

        self.assertTrue(result.ok)
        child_environment = run_mock.call_args.kwargs["env"]
        self.assertNotIn("API_KEY", child_environment)
        self.assertEqual(child_environment["PYTHONUTF8"], "1")

    @patch("runtime_tools.subprocess.run")
    def test_same_execution_id_replays_persisted_result_without_rerun(
        self, run_mock
    ) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=1, stdout="", stderr="KeyError: user_id"
        )
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "state.sqlite3")
            first_token = runtime_tools.activate_runtime_execution("exec-1", database)
            try:
                first = call_runtime({"case_id": "missing_user_id"})
            finally:
                runtime_tools.reset_runtime_execution(first_token)

            second_token = runtime_tools.activate_runtime_execution("exec-1", database)
            try:
                second = call_runtime({"case_id": "missing_user_id"})
            finally:
                runtime_tools.reset_runtime_execution(second_token)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(run_mock.call_count, 1)
        self.assertFalse(first.meta["replayed"])
        self.assertTrue(second.meta["replayed"])
        self.assertEqual(first.data["run_id"], second.data["run_id"])

    @patch("runtime_tools.subprocess.run")
    def test_uncertain_prior_execution_is_not_automatically_repeated(
        self, run_mock
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "state.sqlite3")
            claim, _ = runtime_tools._claim_execution(
                database, "exec-uncertain", "schema_mismatch"
            )
            self.assertEqual(claim, "execute")
            token = runtime_tools.activate_runtime_execution(
                "exec-uncertain", database
            )
            try:
                result = call_runtime({"case_id": "schema_mismatch"})
            finally:
                runtime_tools.reset_runtime_execution(token)

        self.assertFalse(result.ok)
        self.assertEqual(result.meta["reason"], "runtime_execution_indeterminate")
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
