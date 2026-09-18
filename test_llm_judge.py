"""V14.8 LLM Judge 旁路语义评分测试；全部使用假客户端。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import AppConfig, load_config
from evaluation import LLMJudgeResult, score_case
from experiments import run_experiment
from llm_judge import judge_case
from run_evals import format_summary
from test_evaluation import fake_result, missing_user_case


ROOT = Path(__file__).resolve().parent


class FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=40,
                total_tokens=160,
            ),
        )


class FakeClient:
    def __init__(self, content: str):
        self.completions = FakeCompletions(content)
        self.chat = SimpleNamespace(completions=self.completions)


def judge_config() -> AppConfig:
    return AppConfig(
        api_key="diagnosis-key",
        base_url="https://api.deepseek.com/beta",
        model="deepseek-diagnosis",
        output_mode="json_object",
        strict_tools=True,
        judge_enabled=True,
        judge_api_key="judge-key",
        judge_base_url="https://api.deepseek.com/beta",
        judge_model="deepseek-judge",
        judge_output_mode="json_object",
    )


def assessment_json(
    root_cause: int = 5,
    distinction: int = 5,
    fix: int = 4,
    omission: str = "none",
) -> str:
    return json.dumps({
        "root_cause_completeness": root_cause,
        "failure_site_distinction": distinction,
        "fix_actionability": fix,
        "omission_severity": omission,
        "missing_aspects": [],
        "rationale": "根因链完整，且修复建议针对入口校验。",
    }, ensure_ascii=False)


class LLMJudgeTests(unittest.TestCase):
    def test_single_call_returns_structured_semantic_score(self):
        case = missing_user_case()
        evaluation = score_case(case, fake_result(), ROOT)
        client = FakeClient(assessment_json())

        result = judge_case(client, judge_config(), case, evaluation)

        self.assertEqual(len(client.completions.calls), 1)
        request = client.completions.calls[0]
        self.assertNotIn("tools", request)
        self.assertEqual(request["model"], "deepseek-judge")
        self.assertNotIn("obs-001", request["messages"][1]["content"])
        self.assertNotIn("demo_app/app/api.py", request["messages"][1]["content"])
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.semantic_pass)
        self.assertTrue(result.deterministic_pass)
        self.assertEqual(result.total_tokens, 160)
        self.assertEqual(result.average_score, 4.6667)

    def test_invalid_output_is_recorded_without_retry(self):
        case = missing_user_case()
        evaluation = score_case(case, fake_result(), ROOT)
        client = FakeClient("not-json")

        result = judge_case(client, judge_config(), case, evaluation)

        self.assertEqual(len(client.completions.calls), 1)
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.semantic_pass)
        self.assertIn("无效 JSON", result.error or "")
        self.assertEqual(result.total_tokens, 160)

    def test_judge_cannot_override_deterministic_result(self):
        case = missing_user_case()
        failing_agent_result = fake_result(invalid_line=True)

        def judge_runner(_case, evaluation):
            return LLMJudgeResult(
                status="completed",
                model="fake-judge",
                deterministic_pass=evaluation.scores.passed,
                semantic_pass=True,
                average_score=5.0,
                assessment={
                    "root_cause_completeness": 5,
                    "failure_site_distinction": 5,
                    "fix_actionability": 5,
                    "omission_severity": "none",
                    "missing_aspects": [],
                    "rationale": "语义完整。",
                },
            )

        experiment = run_experiment(
            [case],
            lambda _question, _steps, _profile: failing_agent_result,
            ROOT,
            ["full"],
            judge_runner=judge_runner,
        )

        attempt = experiment.attempts[0]
        self.assertFalse(attempt.scores.passed)
        self.assertTrue(attempt.llm_judge.semantic_pass)
        self.assertFalse(attempt.llm_judge.deterministic_pass)
        self.assertEqual(experiment.overall_summary.passed_count, 0)
        self.assertEqual(experiment.overall_summary.judge_semantic_pass_count, 1)
        self.assertIn("旁路语义评分", format_summary(experiment))

    def test_low_judge_score_does_not_revoke_deterministic_pass(self):
        case = missing_user_case()
        evaluation = score_case(case, fake_result(), ROOT)
        result = judge_case(
            FakeClient(assessment_json(3, 2, 2, "major")),
            judge_config(),
            case,
            evaluation,
        )

        self.assertTrue(evaluation.scores.passed)
        self.assertFalse(result.semantic_pass)
        self.assertTrue(result.deterministic_pass)

    def test_config_defaults_to_same_service_and_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "api.env").write_text(
                "\n".join([
                    "API_KEY=main-key",
                    "BASE_URL=https://api.deepseek.com/beta",
                    "MODEL=deepseek-main",
                    "ENABLE_LLM_JUDGE=true",
                    "JUDGE_MODEL=deepseek-reviewer",
                ]),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(root)

        self.assertTrue(config.judge_enabled)
        self.assertEqual(config.judge_api_key, "main-key")
        self.assertEqual(config.judge_base_url, "https://api.deepseek.com/beta")
        self.assertEqual(config.judge_model, "deepseek-reviewer")
        self.assertEqual(config.judge_output_mode, "json_object")


if __name__ == "__main__":
    unittest.main()
