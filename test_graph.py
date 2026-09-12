"""LangGraph 控制流测试；使用假模型，不调用真实 API。"""

import json
import unittest
from types import SimpleNamespace

from config import AppConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from graph import (
    SYSTEM_PROMPT,
    build_agent_graph,
    route_after_model,
    route_after_tools,
    route_after_validation,
    response_usage,
    parse_incident_report,
    tool_call_signature,
)
from tool_profiles import TOOL_PROFILES


VALID_REPORT = json.dumps({
    "summary": "找到问题",
    "root_cause": "测试流程使用的低置信度结论",
    "claims": [],
    "evidence": [],
    "suggested_fixes": ["校验字段"],
    "confidence": "low",
})


def grounded_report(observation_id="obs-001", line_start=1):
    return json.dumps({
        "summary": "读取代码后确认入口存在",
        "root_cause": "测试使用 main.py 入口作为已观察结论",
        "claims": [{
            "claim_id": "C1",
            "statement": "main.py 包含程序入口",
            "evidence_ids": ["E1"],
        }],
        "evidence": [{
            "evidence_id": "E1",
            "observation_id": observation_id,
            "source_type": "code",
            "file": "main.py",
            "line_start": line_start,
            "line_end": line_start,
            "commit_hash": None,
            "description": "main.py 的已读取代码行",
        }],
        "suggested_fixes": [],
        "confidence": "low",
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
        "validation_errors": [],
        "stop_reason": None,
        "tool_call_signatures": [],
        "repeated_tool_call_count": 0,
        "force_synthesis": False,
        "synthesis_attempted": False,
        "repair_attempted": False,
        "observations": [],
        "hypotheses": [],
        "model_call_count": 0,
        "input_token_count": 0,
        "output_token_count": 0,
        "total_token_count": 0,
        "max_model_calls": 10,
        "max_tool_calls": 20,
        "evidence_sufficient": False,
        "early_stopped": False,
        "human_review_enabled": False,
        "human_review_triggered": False,
        "human_review_count": 0,
        "pending_review_reason": None,
        "hitl_model_threshold": 5,
        "hitl_tool_threshold": 10,
        "cancelled": False,
        "hypothesis_update_required": False,
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

    def test_budget_still_executes_last_requested_tool(self):
        state = initial_state(max_steps=1)
        state["step_count"] = 1
        state["messages"].append({"role": "assistant", "tool_calls": [{"id": "1"}]})
        self.assertEqual(route_after_model(state), "execute_tools")

    def test_tool_budget_routes_to_synthesis(self):
        state = initial_state(max_steps=1)
        state["step_count"] = 1
        self.assertEqual(route_after_tools(state), "synthesize_report")

    def test_signature_normalizes_json_key_order(self):
        first = tool_call_signature("search_code", '{"query":"x","path":"."}')
        second = tool_call_signature("search_code", '{"path":".","query":"x"}')
        self.assertEqual(first, second)

    def test_response_usage_supports_provider_usage_objects(self):
        response = SimpleNamespace(usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=30,
            total_tokens=150,
        ))

        self.assertEqual(response_usage(response), (120, 30, 150))
        self.assertEqual(response_usage(SimpleNamespace()), (0, 0, 0))

    def test_report_parser_accepts_markdown_json_fence(self):
        report = parse_incident_report(f"```json\n{VALID_REPORT}\n```")

        self.assertEqual(report.confidence, "low")


class GraphFlowTests(unittest.TestCase):
    def test_tool_result_creates_observation_and_exposes_id(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
            }]),
            FakeMessage(content=grounded_report()),
        ])
        result = build_agent_graph(client, test_config()).invoke(initial_state())

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(len(result["observations"]), 1)
        observation = result["observations"][0]
        self.assertEqual(observation["observation_id"], "obs-001")
        self.assertEqual(observation["sources"][0]["file"], "main.py")
        tool_message = next(
            item for item in result["messages"] if item.get("role") == "tool"
        )
        self.assertIn("obs-001", tool_message["content"])
        second_request_messages = client.fake_completions.requests[1]["messages"]
        self.assertFalse(any(
            item.get("role") == "tool" for item in second_request_messages
        ))
        self.assertTrue(any(
            "压缩调查记忆" in item.get("content", "")
            for item in second_request_messages
        ))

    def test_forged_observation_is_rejected_then_corrected(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
            }]),
            FakeMessage(content=grounded_report("obs-999")),
            FakeMessage(content=grounded_report("obs-001")),
        ])
        result = build_agent_graph(client, test_config()).invoke(initial_state())

        self.assertEqual(result["stop_reason"], "completed")
        self.assertTrue(any(
            item.get("role") == "user" and "诊断验证失败" in item.get("content", "")
            for item in result["messages"]
        ))

    def test_profile_filters_schema_and_blocks_disallowed_execution(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "retrieve_docs",
                    "arguments": '{"query":"user_id","top_k":1}',
                },
            }]),
            FakeMessage(content=VALID_REPORT),
        ])
        app = build_agent_graph(
            client,
            test_config(),
            allowed_tools=TOOL_PROFILES["code_only"],
        )
        result = app.invoke(initial_state())

        schema_names = {
            schema["function"]["name"]
            for schema in client.fake_completions.requests[0]["tools"]
        }
        self.assertEqual(
            schema_names,
            set(TOOL_PROFILES["code_only"]) | {"update_hypotheses"},
        )
        self.assertTrue(any(
            "tool_not_allowed" in message.get("content", "")
            for message in result["messages"]
            if message.get("role") == "tool"
        ))

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
        self.assertEqual(result["report"]["confidence"], "low")
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
        self.assertTrue(result["validation_errors"])
        self.assertIn("root_cause", result["validation_errors"][0])

    def test_new_evidence_requires_hypothesis_update_before_more_tools(self):
        hypothesis_arguments = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "入口文件可能存在配置错误",
                "status": "supported",
                "confidence": 0.6,
                "supporting_observation_ids": ["obs-001"],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "purpose": "读取配置文件交叉验证",
                    "supports_if": "配置不一致",
                    "rejects_if": "配置一致",
                },
            }],
        })
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-2", "type": "function",
                "function": {"name": "search_code", "arguments": '{"query":"main"}'},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-3", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": hypothesis_arguments},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-4", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"config.py"}'},
            }]),
            FakeMessage(content=VALID_REPORT),
        ])

        state = initial_state()
        state["hypotheses"] = [{
            "hypothesis_id": "H0",
            "statement": "先检查入口文件",
            "status": "unverified",
            "confidence": 0.3,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "purpose": "读取入口",
                "supports_if": "入口存在",
                "rejects_if": "入口不存在",
            },
        }]
        result = build_agent_graph(client, test_config()).invoke(state)

        self.assertEqual(result["stop_reason"], "completed")
        self.assertIn("上一轮的新证据尚未写入假设", result["observations"][1]["error"])
        self.assertFalse(any("search_code" in item for item in result["tool_call_signatures"]))
        self.assertTrue(any("config.py" in item for item in result["tool_call_signatures"]))

    def test_max_steps_executes_tool_then_synthesizes_report(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {"name": "list_files", "arguments": '{"path":".","max_depth":1}'},
            }]),
            FakeMessage(content=VALID_REPORT),
        ])
        app = build_agent_graph(client, test_config())
        result = app.invoke(initial_state(max_steps=1))

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(result["report"]["confidence"], "low")
        self.assertEqual(result["tool_call_count"], 1)
        self.assertNotIn("tools", client.fake_completions.requests[-1])

    def test_first_duplicate_tool_call_allows_one_correction_turn(self):
        repeated_call = {
            "id": "call-2",
            "type": "function",
            "function": {"name": "list_files", "arguments": '{"path":".","max_depth":1}'},
        }
        client = FakeClient([
            FakeMessage(tool_calls=[{**repeated_call, "id": "call-1"}]),
            FakeMessage(tool_calls=[repeated_call]),
            FakeMessage(content=VALID_REPORT),
        ])
        app = build_agent_graph(client, test_config())
        result = app.invoke(initial_state())

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(result["repeated_tool_call_count"], 1)
        self.assertFalse(result["synthesis_attempted"])
        self.assertIn("tools", client.fake_completions.requests[-1])
        self.assertTrue(any(
            "duplicate_tool_call" in message.get("content", "")
            for message in result["messages"]
            if message.get("role") == "tool"
        ))

    def test_second_duplicate_tool_call_forces_synthesis(self):
        def repeated_call(call_id):
            return {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "list_files",
                    "arguments": '{"path":".","max_depth":1}',
                },
            }

        client = FakeClient([
            FakeMessage(tool_calls=[repeated_call("call-1")]),
            FakeMessage(tool_calls=[repeated_call("call-2")]),
            FakeMessage(tool_calls=[repeated_call("call-3")]),
            FakeMessage(content=VALID_REPORT),
        ])
        result = build_agent_graph(client, test_config()).invoke(initial_state())

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(result["repeated_tool_call_count"], 2)
        self.assertTrue(result["synthesis_attempted"])
        self.assertNotIn("tools", client.fake_completions.requests[-1])

    def test_invalid_synthesis_gets_one_format_repair(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "list_files",
                    "arguments": '{"path":".","max_depth":1}',
                },
            }]),
            FakeMessage(content='{"summary":"字段不完整"}'),
            FakeMessage(content=VALID_REPORT),
        ])
        result = build_agent_graph(client, test_config()).invoke(initial_state(max_steps=1))

        self.assertEqual(result["stop_reason"], "completed")
        self.assertTrue(result["synthesis_attempted"])
        self.assertTrue(result["repair_attempted"])
        self.assertNotIn("tools", client.fake_completions.requests[-1])

    def test_fallback_preserves_grounded_supported_hypothesis(self):
        client = FakeClient([
            FakeMessage(content='{"summary":"incomplete"}'),
            FakeMessage(content='{"summary":"still incomplete"}'),
            FakeMessage(content='{"summary":"repair failed"}'),
        ])
        state = initial_state(max_steps=1)
        state["observations"] = [{
            "observation_id": "obs-001",
            "tool_call_id": "call-existing",
            "step": 0,
            "tool_name": "read_file",
            "arguments": {"path": "main.py"},
            "ok": True,
            "repeated": False,
            "sources": [{
                "source_type": "code",
                "file": "main.py",
                "line_start": 1,
                "line_end": 1,
                "chunk_id": None,
                "commit_hash": None,
            }],
            "error": None,
            "result_sha256": "digest",
            "result_excerpt": "main.py:1",
            "duration_ms": 1.0,
        }]
        state["hypotheses"] = [{
            "hypothesis_id": "H1",
            "statement": "入口配置存在错误",
            "status": "supported",
            "confidence": 0.7,
            "supporting_observation_ids": ["obs-001"],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "purpose": "读取另一配置文件交叉验证",
                "supports_if": "配置不一致",
                "rejects_if": "配置一致",
            },
        }]

        result = build_agent_graph(client, test_config()).invoke(state)

        self.assertEqual(result["stop_reason"], "invalid_synthesis")
        self.assertEqual(result["report"]["root_cause"], "入口配置存在错误")
        self.assertEqual(result["report"]["confidence"], "medium")
        self.assertEqual(result["report"]["evidence"][0]["observation_id"], "obs-001")
        self.assertEqual(len(result["validation_errors"]), 3)

    def test_confirmed_hypothesis_with_independent_sources_stops_early(self):
        hypothesis_arguments = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "两个代码文件共同确认入口配置错误",
                "status": "confirmed",
                "confidence": 0.9,
                "supporting_observation_ids": ["obs-001", "obs-002"],
                "contradicting_observation_ids": [],
                "next_action": None,
            }],
        })
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-2", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"config.py"}'},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-3", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": hypothesis_arguments},
            }]),
            FakeMessage(content=VALID_REPORT),
        ])

        result = build_agent_graph(client, test_config()).invoke(initial_state())

        self.assertTrue(result["early_stopped"])
        self.assertTrue(result["synthesis_attempted"])
        self.assertEqual(result["hypotheses"][0]["status"], "confirmed")
        self.assertEqual(result["step_count"], 3)

    def test_evidence_confirmed_at_max_step_is_not_counted_as_early_stop(self):
        hypothesis_arguments = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "两个代码文件共同确认入口配置错误",
                "status": "confirmed",
                "confidence": 0.9,
                "supporting_observation_ids": ["obs-001", "obs-002"],
                "contradicting_observation_ids": [],
                "next_action": None,
            }],
        })
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-2", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"config.py"}'},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-3", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": hypothesis_arguments},
            }]),
            FakeMessage(content=VALID_REPORT),
        ])

        result = build_agent_graph(client, test_config()).invoke(
            initial_state(max_steps=3)
        )

        self.assertTrue(result["evidence_sufficient"])
        self.assertFalse(result["early_stopped"])
        self.assertTrue(result["synthesis_attempted"])

    def test_human_review_interrupt_can_resume_into_summary(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1", "type": "function",
                "function": {
                    "name": "list_files",
                    "arguments": '{"path":".","max_depth":1}',
                },
            }]),
            FakeMessage(content=VALID_REPORT),
        ])
        saver = InMemorySaver()
        app = build_agent_graph(client, test_config(), checkpointer=saver)
        state = initial_state()
        state["human_review_enabled"] = True
        state["hitl_tool_threshold"] = 1
        runtime = {"configurable": {"thread_id": "hitl-test"}}

        interrupted = app.invoke(state, config=runtime)
        self.assertIn("__interrupt__", interrupted)

        resumed = app.invoke(
            Command(resume={"action": "summarize"}),
            config=runtime,
        )
        self.assertEqual(resumed["stop_reason"], "completed")
        self.assertEqual(resumed["human_review_count"], 1)
        self.assertTrue(resumed["synthesis_attempted"])

    def test_parallel_tool_calls_cannot_exceed_hard_budget(self):
        client = FakeClient([
            FakeMessage(tool_calls=[
                {
                    "id": "call-1", "type": "function",
                    "function": {
                        "name": "list_files",
                        "arguments": '{"path":".","max_depth":1}',
                    },
                },
                {
                    "id": "call-2", "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"main.py"}',
                    },
                },
            ]),
            FakeMessage(content=VALID_REPORT),
        ])
        state = initial_state()
        state["max_tool_calls"] = 1

        result = build_agent_graph(client, test_config()).invoke(state)

        self.assertEqual(result["tool_call_count"], 2)
        self.assertEqual(len(result["observations"]), 2)
        self.assertTrue(result["observations"][0]["ok"])
        self.assertFalse(result["observations"][1]["ok"])
        self.assertIn("工具调用预算", result["observations"][1]["error"])

    def test_per_step_tool_limit_rejects_excess_without_exhausting_total_budget(self):
        hypothesis_arguments = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "入口配置可能错误",
                "status": "unverified",
                "confidence": 0.4,
                "supporting_observation_ids": [],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "list_files",
                    "purpose": "定位入口文件",
                    "supports_if": "存在入口文件",
                    "rejects_if": "不存在入口文件",
                },
            }],
        })
        client = FakeClient([
            FakeMessage(tool_calls=[
                {
                    "id": "call-h", "type": "function",
                    "function": {
                        "name": "update_hypotheses",
                        "arguments": hypothesis_arguments,
                    },
                },
                {
                    "id": "call-1", "type": "function",
                    "function": {
                        "name": "list_files",
                        "arguments": '{"path":".","max_depth":1}',
                    },
                },
                {
                    "id": "call-2", "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"main.py"}',
                    },
                },
            ]),
            FakeMessage(content=VALID_REPORT),
        ])
        state = initial_state()
        state["max_tools_per_step"] = 1

        result = build_agent_graph(client, test_config()).invoke(state)

        self.assertFalse(result["force_synthesis"])
        self.assertEqual(result["step_count"], 2)
        self.assertEqual(result["tool_call_count"], 3)
        self.assertEqual(len(result["observations"]), 2)
        self.assertTrue(result["observations"][0]["ok"])
        self.assertIn("单轮最多执行 1 个工具", result["observations"][1]["error"])


if __name__ == "__main__":
    unittest.main()
