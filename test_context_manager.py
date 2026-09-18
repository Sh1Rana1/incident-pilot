"""V8.1 上下文压缩和审计状态保留测试。"""

import json
import unittest

from context_manager import compact_messages
from models import DiagnosticHypothesis, ObservedSource, ToolObservation
from provenance import build_observation


def make_observation(index: int, excerpt_size: int = 100) -> ToolObservation:
    return ToolObservation(
        observation_id=f"obs-{index:03d}",
        tool_call_id=f"call-{index}",
        step=index,
        tool_name="read_file",
        arguments={"path": f"file_{index}.py"},
        ok=True,
        sources=[ObservedSource(
            source_type="code",
            file=f"file_{index}.py",
            line_start=1,
            line_end=10,
        )],
        result_sha256=f"digest-{index}",
        result_excerpt="x" * excerpt_size,
        duration_ms=1,
    )


class ContextManagerTests(unittest.TestCase):
    def test_empty_investigation_keeps_original_messages(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
        ]

        compacted, changed = compact_messages(messages, [], [])

        self.assertFalse(changed)
        self.assertIs(compacted, messages)

    def test_compaction_keeps_referenced_and_only_recent_unreferenced_observations(self) -> None:
        observations = [make_observation(index, 2000) for index in range(1, 9)]
        hypothesis = DiagnosticHypothesis(
            hypothesis_id="H1",
            statement="第一个 Observation 支持候选根因",
            status="supported",
            confidence=0.7,
            supporting_observation_ids=["obs-001"],
            next_action={
                "tool_name": "read_file",
                "purpose": "读取第二个文件进行区分",
                "supports_if": "配置值不一致",
                "rejects_if": "配置值一致",
            },
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "tool_calls": [{"id": "call-8"}]},
            {"role": "tool", "tool_call_id": "call-8", "content": "y" * 10000},
        ]

        compacted, changed = compact_messages(messages, observations, [hypothesis])

        self.assertTrue(changed)
        self.assertFalse(any(item.get("role") == "tool" for item in compacted))
        memory = compacted[-1]["content"]
        self.assertIn("obs-001", memory)
        self.assertNotIn("obs-002", memory)
        self.assertIn("obs-008", memory)
        self.assertLess(len(memory), 10000)

    def test_repair_context_keeps_last_plain_assistant_report(self) -> None:
        invalid_report = json.dumps({"summary": "incomplete"})
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": invalid_report},
        ]

        compacted, changed = compact_messages(
            messages,
            [make_observation(1)],
            [],
            include_last_assistant=True,
        )

        self.assertTrue(changed)
        self.assertEqual(compacted[-1]["content"], invalid_report)

    def test_final_report_context_keeps_all_successful_sourced_observations(self) -> None:
        observations = [make_observation(index) for index in range(1, 9)]

        compacted, changed = compact_messages(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "question"},
            ],
            observations,
            [],
            final_report=True,
        )

        self.assertTrue(changed)
        memory = compacted[-1]["content"]
        self.assertIn('"final_report_evidence_mode":true', memory)
        self.assertIn("obs-001", memory)
        self.assertIn("obs-008", memory)

    def test_targeted_read_keeps_tail_line_after_context_compaction(self) -> None:
        lines = [
            {"line": number, "content": "x" * 300}
            for number in range(40, 60)
        ]
        lines[-1]["content"] = "CRITICAL_TAIL_MARKER = payload['user_id']"
        payload = json.dumps({
            "ok": True,
            "data": {"path": "demo_app/run_case.py", "lines": lines},
            "error": None,
            "meta": {},
        })
        observation, _ = build_observation(
            "obs-010",
            "call-10",
            3,
            "read_file",
            json.dumps({
                "path": "demo_app/run_case.py",
                "start_line": 40,
                "end_line": 59,
            }),
            payload,
            1,
        )

        compacted, changed = compact_messages(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "question"},
            ],
            [observation],
            [],
        )

        self.assertTrue(changed)
        self.assertIn("59: CRITICAL_TAIL_MARKER", compacted[-1]["content"])

    def test_non_targeted_observation_keeps_existing_excerpt_limit(self) -> None:
        observation = make_observation(1, 2_000)

        compacted, _ = compact_messages(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "question"},
            ],
            [observation],
            [],
        )
        memory = json.loads(compacted[-1]["content"].split("\n", 1)[1])

        self.assertEqual(len(memory["observations"][0]["result_excerpt"]), 700)


if __name__ == "__main__":
    unittest.main()
