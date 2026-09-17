"""V8 假设状态、引用校验和证据充分性测试。"""

import json
import unittest

from hypotheses import (
    evidence_is_sufficient,
    hypotheses_conflict,
    parse_hypothesis_update,
    validate_hypothesis_readiness,
)
from models import DiagnosticHypothesis, IncidentReport, ObservedSource, ToolObservation
import tools  # noqa: F401 - 注册 next_action 可用的只读工具


def observation(observation_id: str, file: str, source_type: str = "code") -> ToolObservation:
    return ToolObservation(
        observation_id=observation_id,
        tool_call_id=f"call-{observation_id}",
        step=1,
        tool_name="read_file" if source_type == "code" else "retrieve_docs",
        arguments={"path": file},
        ok=True,
        sources=[ObservedSource(
            source_type=source_type,
            file=file,
            line_start=1,
            line_end=5,
        )],
        result_sha256="digest",
        result_excerpt="result",
        duration_ms=1,
    )


class HypothesisTests(unittest.TestCase):
    def test_invalid_low_priority_action_is_ignored_when_another_is_actionable(self) -> None:
        payload = json.dumps({"hypotheses": [
            {
                "hypothesis_id": "H1",
                "statement": "需要定位 API 入口",
                "status": "unverified",
                "confidence": 0.5,
                "supporting_observation_ids": [],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "search_code",
                    "arguments": {"query": "def post_users"},
                    "purpose": "定位入口",
                    "supports_if": "找到入口",
                    "rejects_if": "没有入口",
                },
            },
            {
                "hypothesis_id": "H2",
                "statement": "可能需要运行检查",
                "status": "unverified",
                "confidence": 0.2,
                "supporting_observation_ids": [],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "list_checks",
                    "arguments": {},
                    "purpose": "查看检查",
                    "supports_if": "存在检查",
                    "rejects_if": "不存在检查",
                },
            },
        ]})

        parsed, result = parse_hypothesis_update(
            payload, [], allowed_tools={"read_file", "search_code"}
        )

        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed[1].next_action)
        self.assertIn("ignored_next_actions", result)
        self.assertIn("当前工具 Profile 不允许调用", result)

    def test_open_hypothesis_may_omit_action_when_collection_has_one(self) -> None:
        payload = json.dumps({"hypotheses": [
            {
                "hypothesis_id": "H1",
                "statement": "入口缺少校验",
                "status": "supported",
                "confidence": 0.7,
                "supporting_observation_ids": ["obs-001"],
                "contradicting_observation_ids": [],
                "next_action": None,
            },
            {
                "hypothesis_id": "H2",
                "statement": "需要读取 Service",
                "status": "unverified",
                "confidence": 0.4,
                "supporting_observation_ids": [],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "arguments": {"path": "demo_app/app/service.py"},
                    "purpose": "确认失败点",
                    "supports_if": "直接下标访问",
                    "rejects_if": "已有校验",
                },
            },
        ]})

        parsed, _ = parse_hypothesis_update(
            payload, [observation("obs-001", "demo_app/app/api.py")]
        )

        self.assertIsNotNone(parsed)

    def test_terminal_classification_allows_supported_without_next_action(self) -> None:
        payload = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "API 入口直接下传缺字段 payload",
            "status": "supported",
            "confidence": 0.75,
            "supporting_observation_ids": ["obs-001"],
            "contradicting_observation_ids": [],
            "next_action": None,
        }]})

        parsed, _ = parse_hypothesis_update(
            payload,
            [observation("obs-001", "demo_app/app/api.py")],
            require_next_action=False,
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0].status, "supported")
        self.assertIsNone(parsed[0].next_action)

    def test_next_action_rejects_exact_successful_tool_call(self) -> None:
        prior = ToolObservation(
            observation_id="obs-001",
            tool_call_id="call-1",
            step=1,
            tool_name="search_code",
            arguments={"query": "missing_user_id"},
            ok=True,
            sources=[],
            result_sha256="digest",
            result_excerpt="result",
            duration_ms=1,
        )
        payload = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "入口可能构造了缺字段 payload",
            "status": "unverified",
            "confidence": 0.4,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "search_code",
                "arguments": {"query": "missing_user_id"},
                "purpose": "再次定位入口",
                "supports_if": "找到入口",
                "rejects_if": "没有入口",
            },
        }]})

        parsed, result = parse_hypothesis_update(payload, [prior])

        self.assertIsNone(parsed)
        self.assertIn("next_action 没有新增信息", result)
        self.assertIn("obs-001", result)

    def test_next_action_rejects_read_range_covered_by_prior_observation(self) -> None:
        prior = observation("obs-001", "demo_app/run_case.py")
        prior.arguments = {
            "path": "demo_app/run_case.py",
            "start_line": 1,
            "end_line": 80,
        }
        prior.sources[0].line_end = 80
        payload = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "入口分支需要进一步确认",
            "status": "unverified",
            "confidence": 0.4,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "arguments": {
                    "path": "demo_app/run_case.py",
                    "start_line": 40,
                    "end_line": 60,
                },
                "purpose": "读取入口分支",
                "supports_if": "payload 缺字段",
                "rejects_if": "payload 字段完整",
            },
        }]})

        parsed, result = parse_hypothesis_update(payload, [prior])

        self.assertIsNone(parsed)
        self.assertIn("读取范围已由成功 Observation 覆盖", result)

    def test_next_action_allows_partially_overlapping_read_with_new_lines(self) -> None:
        prior = observation("obs-001", "demo_app/run_case.py")
        prior.arguments = {
            "path": "demo_app/run_case.py",
            "start_line": 1,
            "end_line": 50,
        }
        prior.sources[0].line_end = 50
        payload = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "后续分支可能包含调用信息",
            "status": "unverified",
            "confidence": 0.4,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "arguments": {
                    "path": "demo_app/run_case.py",
                    "start_line": 40,
                    "end_line": 60,
                },
                "purpose": "补充尚未读取的 51–60 行",
                "supports_if": "新行出现调用信息",
                "rejects_if": "新行无关",
            },
        }]})

        parsed, _ = parse_hypothesis_update(payload, [prior])

        self.assertIsNotNone(parsed)

    def test_next_action_arguments_are_validated_against_tool_schema(self) -> None:
        payload = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "需要定向读取入口",
            "status": "unverified",
            "confidence": 0.4,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "arguments": {
                    "path": "demo_app/run_case.py",
                    "start_line": 40,
                    "end_line": 60,
                },
                "purpose": "确认调用参数",
                "supports_if": "入口缺少字段",
                "rejects_if": "入口包含字段",
            },
        }]})

        parsed, _ = parse_hypothesis_update(payload, [])

        self.assertIsNotNone(parsed)

    def test_invalid_next_action_arguments_are_rejected(self) -> None:
        payload = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "读取参数越界",
            "status": "unverified",
            "confidence": 0.4,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "arguments": {"path": "main.py", "start_line": 0, "end_line": 10},
                "purpose": "确认入口",
                "supports_if": "存在入口",
                "rejects_if": "不存在入口",
            },
        }]})

        parsed, result = parse_hypothesis_update(payload, [])

        self.assertIsNone(parsed)
        self.assertIn("next_action 无效", result)
        self.assertIn("工具参数校验失败", result)

    def test_open_hypothesis_requires_structured_next_action(self) -> None:
        payload = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "尚待验证的配置问题",
            "status": "unverified",
            "confidence": 0.4,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": None,
        }]})

        parsed, result = parse_hypothesis_update(payload, [])

        self.assertIsNone(parsed)
        self.assertIn("结构化 next_action", result)

    def test_high_confidence_report_requires_confirmed_hypothesis(self) -> None:
        report = IncidentReport(
            summary="结论",
            root_cause="根因",
            claims=[],
            evidence=[],
            suggested_fixes=[],
            confidence="high",
        )

        self.assertTrue(validate_hypothesis_readiness(report, []))
        confirmed = DiagnosticHypothesis(
            hypothesis_id="H1",
            statement="已确认根因",
            status="confirmed",
            confidence=0.9,
            supporting_observation_ids=["obs-001"],
        )
        self.assertEqual(validate_hypothesis_readiness(report, [confirmed]), [])

    def test_confirmed_hypothesis_requires_real_successful_observations(self) -> None:
        payload = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "配置与文档契约不一致",
            "status": "confirmed",
            "confidence": 0.9,
            "supporting_observation_ids": ["obs-999"],
            "contradicting_observation_ids": [],
            "next_action": None,
        }]})

        parsed, result = parse_hypothesis_update(payload, [])

        self.assertIsNone(parsed)
        self.assertIn("不存在的 Observation", result)

    def test_two_independent_sources_are_sufficient(self) -> None:
        hypotheses = [DiagnosticHypothesis(
            hypothesis_id="H1",
            statement="代码配置违反文档契约",
            status="confirmed",
            confidence=0.9,
            supporting_observation_ids=["obs-001", "obs-002"],
            contradicting_observation_ids=[],
            next_action=None,
        )]
        observations = [
            observation("obs-001", "demo_app/app/webhook.py"),
            observation("obs-002", "demo_app/docs/integrations.md", "documentation"),
        ]

        self.assertTrue(evidence_is_sufficient(hypotheses, observations))

    def test_single_observation_does_not_stop_investigation(self) -> None:
        hypotheses = [DiagnosticHypothesis(
            hypothesis_id="H1",
            statement="单条线索",
            status="confirmed",
            confidence=0.95,
            supporting_observation_ids=["obs-001"],
            contradicting_observation_ids=[],
            next_action=None,
        )]

        self.assertFalse(evidence_is_sufficient(
            hypotheses,
            [observation("obs-001", "main.py")],
        ))

    def test_multiple_confirmed_hypotheses_are_a_conflict(self) -> None:
        hypotheses = [
            DiagnosticHypothesis(
                hypothesis_id=f"H{index}",
                statement=f"候选根因 {index}",
                status="confirmed",
                confidence=0.9,
                supporting_observation_ids=[f"obs-00{index}"],
            )
            for index in (1, 2)
        ]

        self.assertTrue(hypotheses_conflict(hypotheses))


if __name__ == "__main__":
    unittest.main()
