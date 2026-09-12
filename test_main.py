"""命令行多行输入测试；不调用真实模型 API。"""

import unittest
from unittest.mock import patch

import main
from models import IncidentReport


class MultilineInputTests(unittest.TestCase):
    def test_traceback_lines_are_merged_into_one_question(self) -> None:
        entered_lines = iter([
            "Traceback (most recent call last):",
            '  File "demo_app/run_case.py", line 13, in <module>',
            "    from demo_app.app.api import post_users",
            "ModuleNotFoundError: No module named 'demo_app'",
            "",
        ])

        question = main.read_multiline_question(lambda _prompt: next(entered_lines))

        self.assertEqual(question.count("\n"), 3)
        self.assertIn("Traceback (most recent call last):", question)
        self.assertTrue(question.endswith("No module named 'demo_app'"))

    def test_blank_first_line_returns_empty_question(self) -> None:
        self.assertEqual(main.read_multiline_question(lambda _prompt: ""), "")

    def test_eof_submits_collected_lines(self) -> None:
        entered_lines = iter(["KeyError: 'user_id'"])

        def input_then_eof(_prompt: str) -> str:
            try:
                return next(entered_lines)
            except StopIteration as exc:
                raise EOFError from exc

        self.assertEqual(main.read_multiline_question(input_then_eof), "KeyError: 'user_id'")

    @patch("main.format_report", return_value="格式化报告")
    @patch("main.run_agent")
    @patch("main.read_multiline_question")
    def test_main_sends_complete_traceback_to_agent_once(
        self,
        read_question,
        run_agent_mock,
        _format_report,
    ) -> None:
        traceback = "Traceback\n  File example.py\nKeyError: 'user_id'"
        read_question.side_effect = [traceback, "exit"]
        run_agent_mock.return_value = IncidentReport(
            summary="测试",
            root_cause="测试",
            claims=[],
            evidence=[],
            suggested_fixes=[],
            confidence="low",
        )

        main.main()

        run_agent_mock.assert_called_once_with(
            traceback,
            human_review=True,
            review_handler=main.request_human_review,
        )


if __name__ == "__main__":
    unittest.main()
