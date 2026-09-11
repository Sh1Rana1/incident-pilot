"""LangGraph 控制流测试；使用假模型，不调用真实 API。"""

import json
import unittest
from types import SimpleNamespace

from config import AppConfig
from graph import SYSTEM_PROMPT, build_agent_graph, route_after_model, route_after_validation


VALID_REPORT = json.dumps({
    "summary": "找到问题",
    "root_cause": "缺少 user_id",
    "evidence": [{
        "source_type": "code", "file": "main.py", "line": 1, "description": "测试证据"
    }],
    "suggested_fixes": ["校验字段"],
    "confidence": "high",
})


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=True):
        result = {"role": "assistant", "content": self.content, "tool_calls": self.tool_calls}
        return {key: value for key, value in result.items() if value is not None}


class FakeCompletions:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self.messages))])


class FakeClient:
    def __init__(self, messages):
        self.fake_completions = FakeCompletions(messages)
        self.chat = SimpleNamespace(completions=self.fake_completions)


def initial_state(max_steps=8):
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "测试问题"},
        ],
        "step_count": 0,
        "tool_call_count": 0,
        "max_steps": max_steps,
        "report": None,
        "validation_error": None,
        "stop_reason": None,
    }


def test_config():
    return AppConfig(
        api_key="test",
        base_url="https://example.com/v1",
        model="fake-model",
        output_mode="json_object",
        strict_tools=False,
    )


class RoutingTests(unittest.TestCase):
    def test_model_routes_to_tools(self):
        state = initial_state()
        state["step_count"] = 1
        state["messages"].append({"role": "assistant", "tool_calls": [{"id": "1"}]})
        self.assertEqual(route_after_model(state), "execute_tools")

    def test_valid_report_routes_to_end(self):
        state = initial_state()
        state["report"] = json.loads(VALID_REPORT)
        self.assertEqual(route_after_validation(state), "end")

    def test_budget_routes_to_fallback(self):
        state = initial_state(max_steps=1)
        state["step_count"] = 1
        state["messages"].append({"role": "assistant", "tool_calls": [{"id": "1"}]})
        self.assertEqual(route_after_model(state), "build_fallback")


class GraphFlowTests(unittest.TestCase):
    def test_tool_call_then_valid_report(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {"name": "list_files", "arguments": '{"path":".","max_depth":1}'},
            }]),
            FakeMessage(content=VALID_REPORT),
        ])
        app = build_agent_graph(client, test_config())
        result = app.invoke(initial_state())

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(result["step_count"], 2)
        self.assertEqual(result["tool_call_count"], 1)
        self.assertEqual(result["report"]["confidence"], "high")
        self.assertTrue(any(message.get("role") == "tool" for message in result["messages"]))

    def test_invalid_report_is_retried(self):
        client = FakeClient([
            FakeMessage(content='{"summary":"字段不完整"}'),
            FakeMessage(content=VALID_REPORT),
        ])
        app = build_agent_graph(client, test_config())
        result = app.invoke(initial_state())

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(result["step_count"], 2)
        self.assertTrue(any(
            message.get("role") == "user" and "格式错误" in message.get("content", "")
            for message in result["messages"]
        ))

    def test_max_steps_builds_fallback(self):
        client = FakeClient([FakeMessage(tool_calls=[{
            "id": "call-1",
            "type": "function",
            "function": {"name": "list_files", "arguments": '{"path":".","max_depth":1}'},
        }])])
        app = build_agent_graph(client, test_config())
        result = app.invoke(initial_state(max_steps=1))

        self.assertEqual(result["stop_reason"], "max_steps")
        self.assertEqual(result["report"]["confidence"], "low")
        self.assertEqual(result["tool_call_count"], 0)


if __name__ == "__main__":
    unittest.main()
