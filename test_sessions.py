"""V10 持久化会话测试：使用假模型，不消耗真实 API 额度。"""

import subprocess
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import session_agent
from config import AppConfig
from models import HumanReviewRequest
from session_store import SessionStore
from test_graph import FakeClient, FakeMessage, VALID_REPORT


def runtime_config() -> AppConfig:
    return AppConfig(
        api_key="super-secret-key-that-must-not-be-persisted",
        base_url="https://example.com/v1",
        model="fake-model",
        output_mode="json_object",
        strict_tools=False,
        runtime_tools_enabled=True,
    )


class SessionStoreTests(unittest.TestCase):
    def test_v10_database_is_migrated_without_rebuilding_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE incident_sessions (
                    thread_id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tool_profile TEXT NOT NULL,
                    runtime_tools_enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    compute_duration_ms REAL NOT NULL DEFAULT 0,
                    pending_review_json TEXT,
                    result_json TEXT,
                    last_error TEXT
                )
                """
            )
            connection.commit()
            connection.close()

            with SessionStore(path) as store:
                columns = {
                    row["name"]
                    for row in store.connection.execute(
                        "PRAGMA table_info(incident_sessions)"
                    ).fetchall()
                }
                store.create("migrated-thread", "test", "full", False)
                record = store.get("migrated-thread")

        self.assertIn("recalled_memory_ids_json", columns)
        self.assertEqual(record.recalled_memory_ids, [])

    def test_current_runtime_kill_switch_also_applies_when_resuming(self) -> None:
        disabled = runtime_config()
        disabled = AppConfig(**{
            **disabled.__dict__,
            "runtime_tools_enabled": False,
        })
        with tempfile.TemporaryDirectory() as directory:
            with SessionStore(Path(directory) / "state.sqlite3") as store:
                with patch(
                    "session_agent.create_client",
                    return_value=(FakeClient([]), disabled),
                ), patch("session_agent.build_agent_graph") as build_mock:
                    session_agent._build_runtime(store, "full_runtime", True)

        allowed = build_mock.call_args.kwargs["allowed_tools"]
        self.assertNotIn("run_demo_case", allowed)
        self.assertNotIn("list_checks", allowed)
        self.assertNotIn("run_check", allowed)

    def test_session_index_survives_close_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with SessionStore(path) as store:
                store.create("thread-1", "KeyError: user_id", "full_runtime", True)
                request = HumanReviewRequest(
                    reason="runtime_execution",
                    message="是否允许运行 Demo？",
                    model_call_count=1,
                    tool_call_count=0,
                    hypotheses=[],
                    allowed_actions=["approve", "deny", "cancel"],
                )
                store.mark_waiting("thread-1", request)

            with SessionStore(path) as reopened:
                record = reopened.get("thread-1")
                self.assertEqual(record.status, "waiting_for_runtime_approval")
                self.assertEqual(record.pending_review.reason, "runtime_execution")
                self.assertEqual(reopened.list()[0].thread_id, "thread-1")

    @patch("runtime_tools.subprocess.run")
    @patch("session_agent.create_client")
    def test_graph_resumes_after_store_is_closed_and_runtime_runs_once(
        self, create_client_mock, run_mock
    ) -> None:
        first_client = FakeClient([FakeMessage(tool_calls=[{
            "id": "call-runtime-v10",
            "type": "function",
            "function": {
                "name": "run_demo_case",
                "arguments": '{"case_id":"missing_user_id"}',
            },
        }])])
        second_client = FakeClient([FakeMessage(content=VALID_REPORT)])
        create_client_mock.side_effect = [
            (first_client, runtime_config()),
            (second_client, runtime_config()),
        ]
        run_mock.return_value = subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout="",
            stderr="KeyError: 'user_id'",
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with SessionStore(path) as first_store:
                waiting = session_agent.start_session(
                    first_store,
                    "请诊断 user_id 报错",
                    thread_id="durable-thread",
                )
                self.assertEqual(waiting.status, "waiting_for_runtime_approval")

            # 重新打开 Store 模拟原 Python 进程已经结束。
            with SessionStore(path) as second_store:
                completed = session_agent.resume_session(
                    second_store, "durable-thread", "approve"
                )
                self.assertEqual(completed.status, "completed")
                self.assertEqual(completed.result.metrics.runtime_call_count, 1)
                self.assertEqual(
                    completed.result.metrics.successful_runtime_call_count, 1
                )
                self.assertEqual(completed.result.metrics.runtime_approval_count, 1)
                row = second_store.connection.execute(
                    "SELECT status FROM runtime_executions"
                ).fetchone()
                self.assertEqual(row["status"], "completed")

            self.assertEqual(run_mock.call_count, 1)
            self.assertNotIn(
                b"super-secret-key-that-must-not-be-persisted",
                path.read_bytes(),
            )

    def test_invalid_resume_action_is_rejected_before_model_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            with SessionStore(path) as store:
                store.create("thread-2", "test", "full_runtime", True)
                store.mark_waiting(
                    "thread-2",
                    HumanReviewRequest(
                        reason="runtime_execution",
                        message="approve?",
                        model_call_count=1,
                        tool_call_count=0,
                        hypotheses=[],
                        allowed_actions=["approve", "deny", "cancel"],
                    ),
                )
                with patch("session_agent.create_client") as client_mock:
                    with self.assertRaisesRegex(ValueError, "不接受 continue"):
                        session_agent.resume_session(store, "thread-2", "continue")
                    client_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
