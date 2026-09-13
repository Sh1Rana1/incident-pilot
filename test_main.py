"""命令行多行输入测试；不调用真实模型 API。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from models import HumanReviewRequest, IncidentReport


class MultilineInputTests(unittest.TestCase):
    def test_new_parser_supports_detached_mode_and_doctor(self) -> None:
        detached = main._build_parser().parse_args(["new", "--detach"])
        doctor = main._build_parser().parse_args(["doctor"])
        self.assertTrue(detached.detach)
        self.assertEqual(doctor.command, "doctor")

    @patch("main.resume_session")
    @patch("main.request_human_review", side_effect=["approve", "summarize"])
    def test_consecutive_reviews_are_resumed_in_same_process(
        self, _review_mock, resume_mock
    ) -> None:
        request = HumanReviewRequest(
            reason="runtime_execution",
            message="是否运行？",
            model_call_count=1,
            tool_call_count=1,
            hypotheses=[],
            allowed_actions=["approve", "deny", "cancel"],
        )
        waiting = SimpleNamespace(thread_id="thread-stable", pending_review=request)
        second_request = HumanReviewRequest(
            reason="cost_threshold",
            message="是否继续？",
            model_call_count=5,
            tool_call_count=10,
            hypotheses=[],
            allowed_actions=["continue", "summarize", "cancel"],
        )
        waiting_again = SimpleNamespace(
            thread_id="thread-stable", pending_review=second_request
        )
        completed = SimpleNamespace(thread_id="thread-stable", pending_review=None)
        resume_mock.side_effect = [waiting_again, completed]

        result = main._continue_pending_reviews(SimpleNamespace(), waiting)

        self.assertIs(result, completed)
        self.assertEqual(resume_mock.call_count, 2)
        self.assertEqual(resume_mock.call_args_list[0].args[1:], ("thread-stable", "approve"))
        self.assertEqual(
            resume_mock.call_args_list[1].args[1:], ("thread-stable", "summarize")
        )

    @patch("main.resume_session")
    def test_keyboard_interrupt_keeps_waiting_session_for_later_resume(
        self, resume_mock
    ) -> None:
        request = HumanReviewRequest(
            reason="runtime_execution",
            message="是否运行？",
            model_call_count=1,
            tool_call_count=1,
            hypotheses=[],
            allowed_actions=["approve", "deny", "cancel"],
        )
        waiting = SimpleNamespace(thread_id="thread-saved", pending_review=request)

        def interrupt(_prompt: str) -> str:
            raise KeyboardInterrupt

        result = main._continue_pending_reviews(
            SimpleNamespace(), waiting, input_fn=interrupt
        )

        self.assertIs(result, waiting)
        resume_mock.assert_not_called()

    def test_memory_subcommands_are_available(self) -> None:
        args = main._build_parser().parse_args(
            ["memory", "search", "KeyError", "user_id", "--limit", "2"]
        )
        self.assertEqual(args.memory_command, "search")
        self.assertEqual(args.query, ["KeyError", "user_id"])
        self.assertEqual(args.limit, 2)

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
            tool_profile="full_runtime",
            human_review=True,
            review_handler=main.request_human_review,
        )


if __name__ == "__main__":
    unittest.main()
