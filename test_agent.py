"""Agent 公开入口和运行指标测试；不调用真实模型 API。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import agent
from config import AppConfig


REPORT = {
    "summary": "找到问题",
    "root_cause": "缺少字段",
    "claims": [],
    "evidence": [],
    "suggested_fixes": ["校验字段"],
    "confidence": "high",
}


class FakeApp:
    def invoke(self, _state, config):
        self.config = config
        return {
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "question"},
                {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "1",
                        "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
                    }],
                },
                {"role": "tool", "tool_call_id": "1", "content": "result"},
                {"role": "assistant", "content": "report"},
            ],
            "step_count": 2,
            "tool_call_count": 1,
            "tool_call_signatures": ['read_file:{"path":"main.py"}'],
            "repeated_tool_call_count": 0,
            "observations": [],
            "stop_reason": "completed",
            "validation_errors": ["一次测试验证错误"],
            "report": REPORT,
        }


class InterruptingFakeApp(FakeApp):
    def __init__(self):
        self.calls = 0

    def invoke(self, state, config):
        self.calls += 1
        if self.calls == 1:
            return {
                "__interrupt__": [SimpleNamespace(value={
                    "reason": "tool_budget_threshold",
                    "message": "工具调用达到阈值",
                    "model_call_count": 3,
                    "tool_call_count": 10,
                    "hypotheses": [],
                    "allowed_actions": ["continue", "summarize", "cancel"],
                })],
            }
        return super().invoke(state, config)


class AgentEntryTests(unittest.TestCase):
    @patch("agent.build_agent_graph", return_value=FakeApp())
    @patch("agent.create_client")
    def test_detailed_result_contains_metrics(self, create_client, build_graph) -> None:
        create_client.return_value = (
            SimpleNamespace(),
            AppConfig("key", "https://example.com/v1", "model", "text", False),
        )

        result = agent.run_agent_detailed("question", max_steps=4)

        self.assertEqual(result.report.confidence, "high")
        self.assertEqual(result.metrics.model_call_count, 2)
        self.assertEqual(result.metrics.tool_call_count, 1)
        self.assertEqual(result.metrics.observation_count, 0)
        self.assertEqual(result.metrics.tool_names, ["read_file"])
        self.assertEqual(result.metrics.stop_reason, "completed")
        self.assertEqual(result.metrics.tool_profile, "full")
        self.assertEqual(result.validation_errors, ["一次测试验证错误"])
        allowed_tools = build_graph.call_args.kwargs["allowed_tools"]
        self.assertIn("git_status", allowed_tools)

    @patch("agent.run_agent_detailed")
    def test_legacy_run_agent_still_returns_only_report(self, detailed) -> None:
        detailed.return_value = SimpleNamespace(report="report")
        self.assertEqual(agent.run_agent("question"), "report")

    @patch("agent.build_agent_graph")
    @patch("agent.create_client")
    def test_detailed_entry_resumes_native_interrupt(
        self,
        create_client,
        build_graph,
    ) -> None:
        create_client.return_value = (
            SimpleNamespace(),
            AppConfig("key", "https://example.com/v1", "model", "text", False),
        )
        fake_app = InterruptingFakeApp()
        build_graph.return_value = fake_app
        requests = []

        result = agent.run_agent_detailed(
            "question",
            human_review=True,
            review_handler=lambda request: requests.append(request) or "summarize",
        )

        self.assertEqual(fake_app.calls, 2)
        self.assertEqual(requests[0].reason, "tool_budget_threshold")
        self.assertEqual(result.metrics.stop_reason, "completed")


if __name__ == "__main__":
    unittest.main()
