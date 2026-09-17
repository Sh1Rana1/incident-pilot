"""V12.1.1 长期事故记忆测试；只使用本地 SQLite 和假模型。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import session_agent
from memory import format_memory_context, memory_candidate_fields
from models import Evidence
from session_store import SessionStore
from test_evaluation import fake_result
from test_graph import FakeClient, FakeMessage, VALID_REPORT
from test_sessions import runtime_config


class IncidentMemoryTests(unittest.TestCase):
    def test_only_grounded_medium_or_high_reports_become_candidates(self) -> None:
        result = fake_result()
        fields = memory_candidate_fields(
            "KeyError: 'user_id' in create_user",
            result,
        )

        self.assertIsNotNone(fields)
        self.assertIn("KeyError", fields["exception_types"])
        self.assertIn("user_id", fields["symbols"])
        self.assertIn("demo_app/app/service.py", fields["files"])

        low_result = result.model_copy(update={
            "report": result.report.model_copy(update={"confidence": "low"})
        })
        self.assertIsNone(memory_candidate_fields("same", low_result))

    def test_pending_memory_is_not_recalled_until_approved(self) -> None:
        fields = memory_candidate_fields("KeyError: 'user_id'", fake_result())
        with tempfile.TemporaryDirectory() as directory:
            with SessionStore(Path(directory) / "state.sqlite3") as store:
                candidate = store.create_memory_candidate("source-1", fields)
                self.assertEqual(candidate.status, "pending")
                self.assertEqual(store.recall_memories("KeyError user_id"), [])

                approved = store.set_memory_status(candidate.memory_id, "approved")
                matches = store.recall_memories("KeyError user_id")
                self.assertEqual(approved.status, "approved")
                self.assertEqual(matches[0].memory.memory_id, candidate.memory_id)
                self.assertGreater(matches[0].score, 0)

                store.set_memory_status(candidate.memory_id, "rejected")
                self.assertEqual(store.recall_memories("KeyError user_id"), [])

    def test_memory_can_be_forgotten(self) -> None:
        fields = memory_candidate_fields("KeyError: 'user_id'", fake_result())
        with tempfile.TemporaryDirectory() as directory:
            with SessionStore(Path(directory) / "state.sqlite3") as store:
                candidate = store.create_memory_candidate("source-2", fields)
                store.delete_memory(candidate.memory_id)
                with self.assertRaisesRegex(ValueError, "找不到事故记忆"):
                    store.get_memory(candidate.memory_id)

    def test_completed_grounded_session_creates_one_pending_candidate(self) -> None:
        source = fake_result()
        state = {
            "messages": [],
            "report": source.report.model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json") for item in source.observations
            ],
            "hypotheses": [
                item.model_dump(mode="json") for item in source.hypotheses
            ],
            "stop_reason": "completed",
        }
        with tempfile.TemporaryDirectory() as directory:
            with SessionStore(Path(directory) / "state.sqlite3") as store:
                store.create(
                    "completed-source",
                    "KeyError: 'user_id'",
                    "full",
                    False,
                )
                session_agent._persist_outcome(
                    store, "completed-source", state, "full"
                )
                # 重复收尾不会为同一会话创建第二条记忆。
                session_agent._persist_outcome(
                    store, "completed-source", state, "full"
                )
                memories = store.list_memories()

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].status, "pending")
        self.assertEqual(memories[0].source_thread_id, "completed-source")

    def test_recalled_memory_is_labeled_as_hint_not_evidence(self) -> None:
        fields = memory_candidate_fields("KeyError: 'user_id'", fake_result())
        with tempfile.TemporaryDirectory() as directory:
            with SessionStore(Path(directory) / "state.sqlite3") as store:
                candidate = store.create_memory_candidate("source-3", fields)
                store.set_memory_status(candidate.memory_id, "approved")
                matches = store.recall_memories("KeyError user_id")
                context = format_memory_context(matches)

        self.assertIn("只能用于提出候选假设", context)
        self.assertIn("不能作为 Evidence", context)
        self.assertNotIn("observation_id", context)

    @patch("session_agent.create_client")
    def test_new_session_injects_only_approved_similar_memory(
        self, create_client_mock
    ) -> None:
        initial_hypotheses = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "历史线索提示入口可能缺少字段校验",
            "status": "unverified",
            "confidence": 0.3,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "arguments": {"path": "demo_app/app/api.py"},
                "purpose": "用当前项目代码验证历史线索",
                "supports_if": "入口直接透传 payload",
                "rejects_if": "入口已经校验必填字段",
            },
        }]})
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-hypothesis", "type": "function",
                "function": {
                    "name": "update_hypotheses",
                    "arguments": initial_hypotheses,
                },
            }]),
            FakeMessage(content=VALID_REPORT),
        ])
        create_client_mock.return_value = (client, runtime_config())
        fields = memory_candidate_fields("KeyError: 'user_id'", fake_result())
        with tempfile.TemporaryDirectory() as directory:
            with SessionStore(Path(directory) / "state.sqlite3") as store:
                candidate = store.create_memory_candidate("source-4", fields)
                store.set_memory_status(candidate.memory_id, "approved")
                record = session_agent.start_session(
                    store,
                    "KeyError: user_id",
                    tool_profile="full",
                    thread_id="memory-consumer",
                )

        request = client.fake_completions.requests[0]
        system = request["messages"][0]["content"]
        self.assertIn(candidate.memory_id, system)
        self.assertIn("必须用当前项目", system)
        self.assertEqual(record.recalled_memory_ids, [candidate.memory_id])
        self.assertEqual(record.result.metrics.recalled_memory_count, 1)

    def test_memory_cannot_be_declared_as_report_evidence_type(self) -> None:
        with self.assertRaises(ValueError):
            Evidence(
                evidence_id="E1",
                observation_id="mem-001",
                source_type="memory",
                file="",
                line_start=None,
                line_end=None,
                commit_hash=None,
                runtime_id=None,
                description="history",
            )


if __name__ == "__main__":
    unittest.main()
