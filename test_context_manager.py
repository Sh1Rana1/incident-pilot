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
    def test_search_code_compaction_keeps_late_failure_site_match(self) -> None:
        matches = [
            {"path": f"demo_app/app/noise_{index}.py", "line": index,
             "content": "user_id = value" + "x" * 80}
            for index in range(1, 12)
        ]
        matches.append({
            "path": "demo_app/app/service.py",
            "line": 9,
            "content": 'user_id = payload["user_id"]',
        })
        payload = json.dumps({
            "ok": True,
            "data": {"query": "user_id", "matches": matches},
            "error": None,
            "meta": {},
        })
        observation, _ = build_observation(
            "obs-001", "call-search", 1, "search_code",
            json.dumps({"query": "user_id"}), payload, 1,
        )

        compacted, _ = compact_messages(
            [{"role": "system", "content": "system"},
             {"role": "user", "content": "question"}],
            [observation],
            [],
        )

        self.assertIn("demo_app/app/service.py", compacted[-1]["content"])
        self.assertIn("payload", compacted[-1]["content"])

    def test_large_read_keeps_search_hits_and_entry_imports_after_compaction(self) -> None:
        search_payload = json.dumps({
            "ok": True,
            "data": {
                "query": "missing_user_id",
                "matches": [
                    {"path": "demo_app/run_case.py", "line": 46,
                     "content": 'if case_id == "missing_user_id":'},
                ],
            },
            "error": None,
            "meta": {},
        })
        search, _ = build_observation(
            "obs-001", "call-search", 1, "search_code",
            json.dumps({"query": "missing_user_id"}), search_payload, 1,
        )
        read_payload = json.dumps({
            "ok": True,
            "data": {
                "path": "demo_app/run_case.py",
                "lines": [
                    {"line": number, "content": (
                        "from demo_app.app.api import post_users"
                        if number == 13 else
                        'post_users({"email": "demo@example.com"}, create_connection())'
                        if number == 47 else f"line-{number}"
                    )}
                    for number in range(1, 81)
                ],
            },
            "error": None,
            "meta": {},
        })
        read, _ = build_observation(
            "obs-002", "call-read", 2, "read_file",
            json.dumps({
                "path": "demo_app/run_case.py", "start_line": 1, "end_line": 80,
            }),
            read_payload,
            1,
        )

        compacted, _ = compact_messages(
            [{"role": "system", "content": "system"},
             {"role": "user", "content": "question"}],
            [search, read],
            [],
        )

        memory = json.loads(compacted[-1]["content"].split("\n", 1)[1])
        read_memory = next(
            item for item in memory["observations"]
            if item["observation_id"] == "obs-002"
        )
        excerpt = json.loads(read_memory["result_excerpt"])
        retained = {item["line"]: item["content"] for item in excerpt["lines"]}
        self.assertIn("api import post_users", retained[13])
        self.assertIn("demo@example.com", retained[47])
        self.assertEqual(excerpt["selection"], "head_tail_and_search_hit_windows")

    def test_targeted_read_keeps_late_key_lines_after_compaction(self) -> None:
        payload = json.dumps({
            "ok": True,
            "data": {
                "path": "demo_app/run_case.py",
                "lines": [
                    {"line": number, "content": (
                        'post_users({"email": "demo@example.com"}, create_connection())'
                        if number == 46 else f"line-{number}"
                    )}
                    for number in range(40, 61)
                ],
            },
            "error": None,
            "meta": {},
        })
        observation, _ = build_observation(
            "obs-001",
            "call-1",
            1,
            "read_file",
            json.dumps({
                "path": "demo_app/run_case.py",
                "start_line": 40,
                "end_line": 60,
            }),
            payload,
            1,
        )

        compacted, _ = compact_messages(
            [{"role": "system", "content": "system"}, {"role": "user", "content": "question"}],
            [observation],
            [],
        )

        memory = json.loads(compacted[-1]["content"].split("\n", 1)[1])
        excerpt = json.loads(memory["observations"][0]["result_excerpt"])
        line_46 = next(item for item in excerpt["lines"] if item["line"] == 46)
        self.assertIn("demo@example.com", line_46["content"])

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
                "arguments": {"path": "file_2.py", "start_line": 1, "end_line": 10},
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


if __name__ == "__main__":
    unittest.main()
