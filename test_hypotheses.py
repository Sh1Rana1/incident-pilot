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
