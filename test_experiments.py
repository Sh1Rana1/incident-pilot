"""V7 工具 Profile、证据指标和稳定性实验测试；不调用真实模型。"""

import json
import tempfile
import unittest
from pathlib import Path

import tools  # noqa: F401：触发全部工具注册
import runtime_tools  # noqa: F401：触发 V9 Runtime 工具注册
from experiments import run_experiment, save_experiment
from registry import registry
from run_evals import (
    enforce_experiment_cost_guard,
    enforce_judge_cost_guard,
    format_summary,
)
from test_evaluation import fake_result, missing_user_case
from tool_profiles import TOOL_PROFILES, resolve_tool_profile


ROOT = Path(__file__).resolve().parent


class ToolProfileTests(unittest.TestCase):
    def test_profiles_expose_expected_tools(self) -> None:
        self.assertEqual(
            TOOL_PROFILES["code_only"],
            {"list_files", "search_code", "read_file"},
        )
        self.assertIn("retrieve_docs", TOOL_PROFILES["code_rag"])
        self.assertNotIn("git_status", TOOL_PROFILES["code_rag"])
        self.assertIn("git_status", TOOL_PROFILES["full"])
        self.assertNotIn("run_demo_case", TOOL_PROFILES["full"])
        self.assertIn("run_demo_case", TOOL_PROFILES["full_runtime"])
        self.assertIn("list_checks", TOOL_PROFILES["full_runtime"])
        self.assertIn("run_check", TOOL_PROFILES["full_runtime"])

    def test_schema_is_filtered_by_profile(self) -> None:
        allowed = resolve_tool_profile("code_only")[1]
        schema_names = {
            schema["function"]["name"]
            for schema in registry.schemas(allowed_tools=allowed)
        }
        self.assertEqual(schema_names, set(allowed))

    def test_execution_layer_rejects_disallowed_tool(self) -> None:
        allowed = resolve_tool_profile("code_only")[1]
        result = registry.execute(
            "retrieve_docs",
            '{"query":"user_id","top_k":1}',
            allowed_tools=allowed,
        )
        self.assertIn("tool_not_allowed", result)

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "未知工具 Profile"):
            resolve_tool_profile("unknown")


class ExperimentTests(unittest.TestCase):
    def test_cost_guard_requires_explicit_confirmation_above_three_runs(self) -> None:
        enforce_experiment_cost_guard(3, confirmed=False)
        enforce_experiment_cost_guard(54, confirmed=True)
        with self.assertRaisesRegex(SystemExit, "费用保护"):
            enforce_experiment_cost_guard(4, confirmed=False)

    def test_judge_cost_guard_requires_confirmation_above_three_calls(self) -> None:
        enforce_judge_cost_guard(3, confirmed=False)
        enforce_judge_cost_guard(15, confirmed=True)
        with self.assertRaisesRegex(SystemExit, "Judge 费用保护"):
            enforce_judge_cost_guard(4, confirmed=False)

    def test_profiles_and_repeated_runs_are_aggregated(self) -> None:
        calls: list[tuple[str, int, str]] = []

        def runner(question: str, max_steps: int, profile: str):
            calls.append((question, max_steps, profile))
            result = fake_result()
            metrics = result.metrics.model_copy(update={
                "tool_profile": profile,
                "tool_names": ["read_file"] if profile == "code_only" else ["retrieve_docs"],
            })
            return result.model_copy(update={"metrics": metrics})

        experiment = run_experiment(
            [missing_user_case()],
            runner,
            ROOT,
            ["code_only", "code_rag"],
            runs_per_case=2,
            max_steps=5,
        )

        self.assertEqual(len(calls), 4)
        self.assertEqual(len(experiment.attempts), 4)
        self.assertEqual([item.run_index for item in experiment.attempts], [1, 2, 1, 2])
        self.assertEqual(len(experiment.profile_summaries), 2)
        self.assertEqual(len(experiment.case_summaries), 2)
        self.assertEqual(experiment.case_summaries[0].case_id, "missing_user_id")
        self.assertEqual(experiment.profile_summaries[0].pass_rate, 1.0)
        self.assertEqual(
            experiment.profile_summaries[0].tool_usage_counts,
            {"read_file": 2},
        )
        self.assertEqual(experiment.overall_summary.attempt_count, 4)

        summary_text = format_summary(experiment)
        self.assertIn("Profile 对照", summary_text)
        self.assertIn("按案例稳定性", summary_text)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "experiment.json"
            save_experiment(experiment, output)
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["case_summaries"]), 2)
        self.assertEqual(
            saved["attempts"][0]["observations"][0]["observation_id"],
            "obs-001",
        )

    def test_duplicate_profiles_and_invalid_runs_are_rejected(self) -> None:
        runner = lambda _question, _steps, _profile: fake_result()
        with self.assertRaisesRegex(ValueError, "不能重复"):
            run_experiment(
                [missing_user_case()], runner, ROOT, ["full", "full"]
            )
        with self.assertRaisesRegex(ValueError, "大于等于 1"):
            run_experiment(
                [missing_user_case()], runner, ROOT, ["full"], runs_per_case=0
            )

    def test_saved_experiment_is_never_overwritten(self) -> None:
        experiment = run_experiment(
            [missing_user_case()], lambda _q, _m, _p: fake_result(), ROOT, ["full"]
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "baseline.json"
            save_experiment(experiment, output)
            original = output.read_bytes()
            with self.assertRaisesRegex(FileExistsError, "拒绝覆盖"):
                save_experiment(experiment, output)
            self.assertEqual(output.read_bytes(), original)

    def test_terminal_summary_explains_failed_attempt(self) -> None:
        experiment = run_experiment(
            [missing_user_case()],
            lambda _question, _steps, _profile: fake_result(invalid_line=True),
            ROOT,
            ["full"],
        )

        summary = format_summary(experiment)
        self.assertIn("失败原因", summary)
        self.assertIn("invalid_citations:1", summary)


if __name__ == "__main__":
    unittest.main()
