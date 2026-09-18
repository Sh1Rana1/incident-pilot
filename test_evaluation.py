"""V7 确定性评分、Evidence 落地与 Claim 覆盖测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from evaluation import (
    EvaluationCase,
    load_cases,
    run_evaluation,
    save_evaluation,
    score_case,
)
from models import (
    AgentRunResult,
    DiagnosticClaim,
    DiagnosticHypothesis,
    Evidence,
    IncidentReport,
    ObservedSource,
    RunMetrics,
    ToolObservation,
)


ROOT = Path(__file__).resolve().parent


def fake_result(invalid_line: bool = False) -> AgentRunResult:
    observations = [
        ToolObservation(
            observation_id="obs-001", tool_call_id="call-1", step=1,
            tool_name="read_file", arguments={"path": "demo_app/app/api.py"},
            ok=True, sources=[ObservedSource(
                source_type="code", file="demo_app/app/api.py", line_start=1, line_end=20,
            )], result_sha256="a", result_excerpt="api", duration_ms=1,
        ),
        ToolObservation(
            observation_id="obs-002", tool_call_id="call-2", step=2,
            tool_name="read_file", arguments={"path": "demo_app/app/service.py"},
            ok=True, sources=[ObservedSource(
                source_type="code", file="demo_app/app/service.py", line_start=1, line_end=20,
            )], result_sha256="b", result_excerpt="service", duration_ms=1,
        ),
        ToolObservation(
            observation_id="obs-003", tool_call_id="call-3", step=3,
            tool_name="retrieve_docs", arguments={"query": "user_id", "top_k": 1},
            ok=True, sources=[ObservedSource(
                source_type="documentation", file="demo_app/docs/api.md",
                line_start=1, line_end=20, chunk_id="chunk-1",
            )], result_sha256="c", result_excerpt="docs", duration_ms=1,
        ),
    ]
    return AgentRunResult(
        report=IncidentReport(
            summary="KeyError: user_id",
            root_cause="API 层没有校验 user_id，Service 直接读取该字段。",
            claims=[DiagnosticClaim(
                claim_id="C1",
                statement="API 缺少校验导致 Service 直接读取缺失字段",
                evidence_ids=["E1", "E2", "E3"],
            )],
            evidence=[
                Evidence(
                    evidence_id="E1", observation_id="obs-001",
                    source_type="code",
                    file="demo_app/app/api.py",
                    line_start=9999 if invalid_line else 9,
                    line_end=9999 if invalid_line else 9,
                    commit_hash=None,
                    runtime_id=None,
                    description="API 未校验字段",
                ),
                Evidence(
                    evidence_id="E2", observation_id="obs-002",
                    source_type="code",
                    file="demo_app/app/service.py",
                    line_start=10,
                    line_end=10,
                    commit_hash=None,
                    runtime_id=None,
                    description="直接读取 user_id",
                ),
                Evidence(
                    evidence_id="E3", observation_id="obs-003",
                    source_type="documentation",
                    file="demo_app/docs/api.md",
                    line_start=1,
                    line_end=1,
                    commit_hash=None,
                    runtime_id=None,
                    description="接口约定",
                ),
            ],
            suggested_fixes=["在 API 层校验 user_id"],
            confidence="high",
        ),
        metrics=RunMetrics(
            tool_profile="full",
            model_call_count=3,
            investigation_step_count=3,
            tool_call_count=4,
            unique_tool_call_count=4,
            repeated_tool_call_count=0,
            observation_count=3,
            successful_observation_count=3,
            synthesis_used=False,
            tool_names=["search_code", "read_file", "read_file", "retrieve_docs"],
            stop_reason="completed",
            duration_ms=125.5,
        ),
        observations=observations,
        hypotheses=[DiagnosticHypothesis(
            hypothesis_id="H1",
            statement="API 缺少校验导致 Service 读取缺失字段",
            status="confirmed",
            confidence=0.9,
            supporting_observation_ids=["obs-001", "obs-002"],
            contradicting_observation_ids=[],
            next_action=None,
        )],
    )


def missing_user_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="missing_user_id",
        question="KeyError: user_id",
        expected_exception="KeyError",
        root_cause_keywords=["API", "校验", "user_id"],
        evidence_files=["demo_app/app/api.py", "demo_app/app/service.py"],
        relevant_docs=["demo_app/docs/api.md"],
    )


class ScoringTests(unittest.TestCase):
    def test_matching_report_passes_with_full_scores(self) -> None:
        result = score_case(missing_user_case(), fake_result(), ROOT)

        self.assertTrue(result.scores.passed)
        self.assertEqual(result.scores.root_cause_keyword_rate, 1.0)
        self.assertEqual(result.scores.evidence_file_rate, 1.0)
        self.assertEqual(result.scores.relevant_doc_rate, 1.0)
        self.assertEqual(result.scores.citation_validity_rate, 1.0)

    def test_nonexistent_line_invalidates_citation_and_case(self) -> None:
        result = score_case(missing_user_case(), fake_result(invalid_line=True), ROOT)

        self.assertFalse(result.scores.passed)
        self.assertEqual(result.scores.invalid_citations, 1)
        self.assertLess(result.scores.citation_validity_rate, 1.0)

    def test_missing_expected_exception_fails_case(self) -> None:
        base = fake_result()
        report = base.report.model_copy(update={
            "summary": "用户创建请求失败",
            "root_cause": "API 层没有校验 user_id，Service 直接读取该字段。",
        })

        result = score_case(
            missing_user_case(),
            base.model_copy(update={"report": report}),
            ROOT,
        )

        self.assertFalse(result.scores.expected_exception_mentioned)
        self.assertFalse(result.scores.passed)
        self.assertIn(
            "missing_expected_exception:KeyError",
            result.scores.failure_reasons,
        )

    def test_partial_required_code_coverage_fails_case(self) -> None:
        base = fake_result()
        report = base.report.model_copy(update={
            "claims": [base.report.claims[0].model_copy(update={
                "evidence_ids": ["E1", "E3"],
            })],
            "evidence": [base.report.evidence[0], base.report.evidence[2]],
        })

        result = score_case(
            missing_user_case(),
            base.model_copy(update={"report": report}),
            ROOT,
        )

        self.assertEqual(result.scores.evidence_file_rate, 0.5)
        self.assertFalse(result.scores.passed)
        self.assertIn("insufficient_evidence_files", result.scores.failure_reasons)

    def test_empty_evidence_does_not_receive_perfect_citation_rate(self) -> None:
        base = fake_result()
        empty_report = base.report.model_copy(update={
            "claims": [],
            "evidence": [],
            "confidence": "low",
        })

        result = score_case(
            missing_user_case(),
            base.model_copy(update={"report": empty_report}),
            ROOT,
        )

        self.assertEqual(result.scores.valid_citations, 0)
        self.assertEqual(result.scores.citation_validity_rate, 0.0)

    def test_document_score_requires_rag_tool_usage(self) -> None:
        base = fake_result()
        report = base.report.model_copy(update={
            "claims": [base.report.claims[0].model_copy(update={
                "evidence_ids": ["E1", "E2"],
            })],
            "evidence": base.report.evidence[:2],
        })
        without_rag = base.model_copy(update={
            "report": report,
            "observations": base.observations[:2],
            "metrics": base.metrics.model_copy(update={
                "tool_profile": "code_only",
                "tool_names": ["read_file"],
                "observation_count": 2,
                "successful_observation_count": 2,
            })
        })
        result = score_case(missing_user_case(), without_rag, ROOT)
        self.assertEqual(result.scores.relevant_doc_rate, 0.0)
        self.assertTrue(result.scores.passed)

    def test_runtime_required_case_needs_grounded_runtime_evidence(self) -> None:
        case = missing_user_case().model_copy(update={
            "requires_runtime_evidence": True,
        })
        base = fake_result()
        missing = score_case(case, base, ROOT)
        self.assertFalse(missing.scores.passed)
        self.assertIn("missing_runtime_evidence", missing.scores.failure_reasons)

        runtime_observation = ToolObservation(
            observation_id="obs-004", tool_call_id="call-4", step=4,
            tool_name="run_demo_case", arguments={"case_id": "missing_user_id"},
            ok=True,
            sources=[ObservedSource(
                source_type="runtime", file="", runtime_id="runtime-test-001",
            )],
            result_sha256="d", result_excerpt="KeyError: user_id", duration_ms=2,
        )
        runtime_evidence = Evidence(
            evidence_id="E4", observation_id="obs-004", source_type="runtime",
            file="", line_start=None, line_end=None, commit_hash=None,
            runtime_id="runtime-test-001", description="本地复现得到 KeyError",
        )
        report = base.report.model_copy(update={
            "evidence": [*base.report.evidence, runtime_evidence],
            "claims": [base.report.claims[0].model_copy(update={
                "evidence_ids": [*base.report.claims[0].evidence_ids, "E4"],
            })],
        })
        metrics = base.metrics.model_copy(update={
            "runtime_call_count": 1,
            "successful_runtime_call_count": 1,
        })
        grounded = score_case(
            case,
            base.model_copy(update={
                "report": report,
                "observations": [*base.observations, runtime_observation],
                "metrics": metrics,
            }),
            ROOT,
        )
        self.assertTrue(grounded.scores.passed)
        self.assertEqual(grounded.scores.runtime_evidence_count, 1)

    def test_numeric_keyword_with_unit_does_not_match_line_number(self) -> None:
        case = missing_user_case().model_copy(update={
            "root_cause_keywords": ["timeout_seconds", "30 秒", "10 秒"],
        })
        base = fake_result()
        report = base.report.model_copy(update={
            "summary": "timeout_seconds 配置不符合外部约束",
            "root_cause": "当前值为 30 秒；校验调用位于第 10 行，但上限未知。",
        })
        result = score_case(
            case,
            base.model_copy(update={"report": report}),
            ROOT,
        )

        self.assertEqual(result.scores.root_cause_keyword_rate, 0.6667)
        self.assertIn(
            "missing_root_cause_keywords:10 秒",
            result.scores.failure_reasons,
        )

    def test_root_cause_keyword_in_diagnostic_claim_is_counted(self) -> None:
        case = missing_user_case().model_copy(update={
            "root_cause_keywords": ["timeout_seconds", "30 秒", "10 秒"],
        })
        base = fake_result()
        report = base.report.model_copy(update={
            "summary": "timeout_seconds 配置违反供应商约束",
            "root_cause": "当前配置 30 大于 v2 上限 10。",
            "claims": [base.report.claims[0].model_copy(update={
                "statement": "旧值为 30 秒，而 v2 上限为 10 秒。",
            })],
        })

        result = score_case(case, base.model_copy(update={"report": report}), ROOT)

        self.assertEqual(result.scores.root_cause_keyword_rate, 1.0)
        self.assertNotIn(
            "missing_root_cause_keywords:30 秒",
            result.scores.failure_reasons,
        )

    def test_batch_summary_uses_injected_runner(self) -> None:
        calls: list[tuple[str, int]] = []

        def runner(question: str, max_steps: int) -> AgentRunResult:
            calls.append((question, max_steps))
            return fake_result()

        evaluation = run_evaluation([missing_user_case()], runner, ROOT, max_steps=5)

        self.assertEqual(calls, [("KeyError: user_id", 5)])
        self.assertEqual(evaluation.summary.pass_rate, 1.0)
        self.assertEqual(evaluation.summary.average_model_call_count, 3.0)

    def test_load_filter_and_save_json(self) -> None:
        cases = load_cases(ROOT / "demo_app" / "evals", {"schema_mismatch"})
        self.assertEqual([case.case_id for case in cases], ["schema_mismatch"])

        evaluation = run_evaluation([missing_user_case()], lambda _q, _m: fake_result(), ROOT)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            save_evaluation(evaluation, output)
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["passed_count"], 1)
        self.assertEqual(
            saved["cases"][0]["observations"][0]["observation_id"],
            "obs-001",
        )


if __name__ == "__main__":
    unittest.main()
