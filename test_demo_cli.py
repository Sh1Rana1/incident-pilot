"""V14.10 演示目录、Markdown 渲染和不可覆盖输出测试。"""

import tempfile
import unittest
from pathlib import Path

from demo_app.run_case import CASES
from demo_cli import (
    DEMO_CASES,
    choose_demo_case,
    format_demo_markdown,
    load_demo_question,
    resolve_demo_output,
    save_demo_markdown,
    validate_demo_catalog,
)
from session_store import SessionRecord
from test_evaluation import fake_result


ROOT = Path(__file__).resolve().parent


class DemoCliTests(unittest.TestCase):
    def test_catalog_matches_every_executable_case_and_log(self) -> None:
        validate_demo_catalog(ROOT)
        self.assertEqual(tuple(item.case_id for item in DEMO_CASES), CASES)

    def test_question_uses_public_log_without_evaluation_answer(self) -> None:
        question = load_demo_question("missing_user_id", ROOT)

        self.assertIn("KeyError: 'user_id'", question)
        self.assertIn("区分直接报错点和系统根因", question)
        self.assertNotIn("demo_app/evals", question)
        self.assertNotIn("root_cause_keywords", question)

    def test_interactive_selection_accepts_number_and_cancel(self) -> None:
        self.assertEqual(
            choose_demo_case(input_fn=lambda _prompt: "1"),
            "missing_user_id",
        )
        self.assertIsNone(choose_demo_case(input_fn=lambda _prompt: "q"))

    def test_completed_record_renders_claim_evidence_and_trace(self) -> None:
        record = SessionRecord(
            thread_id="demo-thread-001",
            question=load_demo_question("missing_user_id", ROOT),
            status="completed",
            tool_profile="full",
            runtime_tools_enabled=False,
            created_at="2026-09-19T00:00:00+00:00",
            updated_at="2026-09-19T00:01:00+00:00",
            compute_duration_ms=1_500,
            result=fake_result(),
        )

        rendered = format_demo_markdown("missing_user_id", record)

        self.assertIn("# IncidentPilot 演示报告", rendered)
        self.assertIn("Claim–Evidence Ledger", rendered)
        self.assertIn("demo_app/app/api.py:9", rendered)
        self.assertIn("obs-001", rendered)
        self.assertIn("调查轨迹", rendered)
        self.assertIn("正式工作区", rendered)

    def test_output_is_scoped_to_demo_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = resolve_demo_output(
                "missing_user_id", "12345678-rest", project_root=root
            )
            self.assertEqual(
                output,
                root / ".incident_reports" / "demos" /
                "demo-missing_user_id-12345678.md",
            )
            with self.assertRaisesRegex(ValueError, "只能写入"):
                resolve_demo_output(
                    "missing_user_id",
                    "thread",
                    requested=Path("outside.md"),
                    project_root=root,
                )

    def test_existing_markdown_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo.md"
            save_demo_markdown("first", output)
            with self.assertRaisesRegex(FileExistsError, "拒绝覆盖"):
                save_demo_markdown("second", output)
            self.assertEqual(output.read_text(encoding="utf-8"), "first")


if __name__ == "__main__":
    unittest.main()
