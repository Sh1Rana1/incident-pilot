"""LangGraph 控制流测试；使用假模型，不调用真实 API。"""

import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import AppConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from graph import (
    SYSTEM_PROMPT,
    _covered_read_observation,
    _next_action_catalog,
    _select_next_action,
    build_agent_graph,
    build_report_output_contract,
    route_after_model,
    route_after_tools,
    route_after_validation,
    response_usage,
    parse_incident_report,
    tool_call_signature,
)
from models import (
    DiagnosticHypothesis,
    ObservedSource,
    PatchVerificationResult,
    ToolObservation,
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
            "runtime_id": None,
            "description": "main.py 的已读取代码行",
        }],
        "suggested_fixes": [],
        "confidence": "low",
    })


def classify_observations_message(
    observation_ids,
    *,
    call_id="call-classify",
    next_path="config.py",
):
    return FakeMessage(tool_calls=[{
        "id": call_id,
        "type": "function",
        "function": {
            "name": "update_hypotheses",
            "arguments": json.dumps({"hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "现有 Observation 支持待继续验证的候选根因",
                "status": "supported",
                "confidence": 0.65,
                "supporting_observation_ids": list(observation_ids),
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "arguments": {"path": next_path},
                    "purpose": "读取尚未调查的文件进行交叉验证",
                    "supports_if": "新文件支持当前候选根因",
                    "rejects_if": "新文件否定当前候选根因",
                },
            }]}),
        },
    }])


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
        "final_classification_used": False,
        "runtime_tools_enabled": False,
        "runtime_execution_preapproved": False,
        "runtime_execution_decision": None,
        "runtime_call_count": 0,
        "successful_runtime_call_count": 0,
        "runtime_timeout_count": 0,
        "runtime_approval_count": 0,
        "runtime_denial_count": 0,
        "runtime_replay_count": 0,
        "max_runtime_calls": 1,
        "runtime_ledger_path": None,
        "thread_id": "test-thread",
        "recalled_memory_count": 0,
        "patch_requested": False,
        "patch_attempted": False,
        "patch_proposal": None,
        "patch_validation_errors": [],
    }


def state_with_existing_hypothesis(max_steps=8):
    """供与初始建模无关的控制流测试直接进入外部调查阶段。"""
    state = initial_state(max_steps=max_steps)
    state["hypotheses"] = [{
        "hypothesis_id": "H0",
        "statement": "测试夹具已完成初始建模",
        "status": "confirmed",
        "confidence": 0.1,
        "supporting_observation_ids": [],
        "contradicting_observation_ids": [],
        "next_action": None,
    }]
    return state


def test_config():
    return AppConfig(
        api_key="test",
        base_url="https://example.com/v1",
        model="fake-model",
        output_mode="json_object",
        strict_tools=False,
    )


class RoutingTests(unittest.TestCase):
    def test_read_range_fully_covered_by_prior_observation_is_duplicate(self):
        observations = [
            ToolObservation(
                observation_id=f"obs-00{index}",
                tool_call_id=f"call-{index}",
                step=index,
                tool_name="read_file",
                arguments={
                    "path": "demo_app/run_case.py",
                    "start_line": start,
                    "end_line": end,
                },
                ok=True,
                sources=[ObservedSource(
                    source_type="code",
                    file="demo_app/run_case.py",
                    line_start=start,
                    line_end=end,
                )],
                result_sha256=f"digest-{index}",
                result_excerpt="excerpt",
                duration_ms=1,
            )
            for index, (start, end) in enumerate(((1, 30), (31, 120)), 1)
        ]

        covered = _covered_read_observation(
            "read_file",
            '{"path":"demo_app/run_case.py","start_line":40,"end_line":60}',
            observations,
        )

        self.assertIs(covered, observations[1])

    def test_partially_overlapping_read_with_new_lines_is_allowed(self):
        observed = ToolObservation(
            observation_id="obs-001",
            tool_call_id="call-1",
            step=1,
            tool_name="read_file",
            arguments={"path": "demo_app/run_case.py", "start_line": 1, "end_line": 50},
            ok=True,
            sources=[ObservedSource(
                source_type="code",
                file="demo_app/run_case.py",
                line_start=1,
                line_end=50,
            )],
            result_sha256="digest",
            result_excerpt="excerpt",
            duration_ms=1,
        )

        covered = _covered_read_observation(
            "read_file",
            '{"path":"demo_app/run_case.py","start_line":40,"end_line":60}',
            [observed],
        )

        self.assertIsNone(covered)

    def test_report_contract_has_schema_and_only_real_observations(self):
        state = state_with_existing_hypothesis()
        state["observations"] = [{
            "observation_id": "obs-001",
            "tool_call_id": "call-1",
            "step": 1,
            "tool_name": "read_file",
            "arguments": {"path": "main.py"},
            "ok": True,
            "repeated": False,
            "sources": [{
                "source_type": "code", "file": "main.py",
                "line_start": 1, "line_end": 2,
                "chunk_id": None, "commit_hash": None, "runtime_id": None,
            }],
            "error": None,
            "result_sha256": "digest",
            "result_excerpt": "excerpt",
            "duration_ms": 1.0,
        }]

        contract = build_report_output_contract(state)

        self.assertIn("suggested_fixes 必须是字符串数组", contract)
        self.assertIn('"additionalProperties":false', contract)
        self.assertIn("obs-001", contract)
        self.assertIn("Claim.evidence_ids", contract)

    def test_model_routes_to_tools(self):
        state = initial_state()
        state["step_count"] = 1
        state["messages"].append({"role": "assistant", "tool_calls": [{"id": "1"}]})
        self.assertEqual(route_after_model(state), "execute_tools")

    def test_valid_report_routes_to_end(self):
        state = initial_state()
        state["report"] = json.loads(VALID_REPORT)
        self.assertEqual(route_after_validation(state), "end")

    def test_valid_report_routes_to_patch_only_when_requested(self):
        state = initial_state()
        state["report"] = json.loads(VALID_REPORT)
        state["stop_reason"] = "completed"
        state["patch_requested"] = True
        self.assertEqual(route_after_validation(state), "propose_patch")

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

    def test_report_parser_repairs_unescaped_code_quotes_locally(self):
        payload = json.loads(VALID_REPORT)
        payload["root_cause"] = 'Service 使用 payload["user_id"] 读取必填字段'
        malformed = json.dumps(payload, ensure_ascii=False).replace(
            'payload[\\"user_id\\"]',
            'payload["user_id"]',
        )

        report = parse_incident_report(malformed)

        self.assertIn('payload["user_id"]', report.root_cause)

    def test_report_parser_repairs_missing_member_comma_locally(self):
        malformed = VALID_REPORT.replace(
            '", "root_cause"',
            '" "root_cause"',
            1,
        )

        report = parse_incident_report(malformed)

        self.assertEqual(report.confidence, "low")


class GraphFlowTests(unittest.TestCase):
    @patch("graph.verify_patch_in_sandbox")
    def test_validated_patch_requires_approval_before_sandbox_verification(
        self,
        verify_mock,
    ):
        hypothesis_arguments = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "API 入口缺少 user_id 校验",
                "status": "supported",
                "confidence": 0.75,
                "supporting_observation_ids": ["obs-001"],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "arguments": {"path": "demo_app/app/service.py"},
                    "purpose": "检查下游失败站点",
                    "supports_if": "Service 直接读取必填字段",
                    "rejects_if": "Service 已处理缺失字段",
                },
            }],
        })
        report = json.dumps({
            "summary": "API 缺少字段校验",
            "root_cause": "API 直接传递未校验 payload",
            "claims": [{
                "claim_id": "C1",
                "statement": "API 没有检查 user_id",
                "evidence_ids": ["E1"],
            }],
            "evidence": [{
                "evidence_id": "E1",
                "observation_id": "obs-001",
                "source_type": "code",
                "file": "demo_app/app/api.py",
                "line_start": 8,
                "line_end": 10,
                "commit_hash": None,
                "runtime_id": None,
                "description": "API 直接调用 Service",
            }],
            "suggested_fixes": ["增加输入校验"],
            "confidence": "medium",
        })
        diff = (
            "diff --git a/demo_app/app/api.py b/demo_app/app/api.py\n"
            "--- a/demo_app/app/api.py\n"
            "+++ b/demo_app/app/api.py\n"
            "@@ -8,3 +8,5 @@\n"
            " def post_users(payload: dict, connection: sqlite3.Connection) -> dict:\n"
            "+    if \"user_id\" not in payload:\n"
            "+        return {\"status\": 400, \"error\": \"missing user_id\"}\n"
            "     create_user(payload, connection)\n"
            "     return {\"status\": 201}"
        )
        proposal = json.dumps({
            "diagnosis_claim_ids": ["C1"],
            "changed_files": ["demo_app/app/api.py"],
            "unified_diff": diff,
            "rationale": "在 API 边界验证必填字段",
            "risks": ["需要确认 400 或 422 契约"],
            "verification_check_ids": ["demo_smoke_suite"],
        })
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-read", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"demo_app/app/api.py"}',
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-hypothesis", "type": "function",
                "function": {
                    "name": "update_hypotheses",
                    "arguments": hypothesis_arguments,
                },
            }]),
            FakeMessage(content=report),
            FakeMessage(content=proposal),
        ])
        state = state_with_existing_hypothesis()
        state["patch_requested"] = True
        state["patch_verification_requested"] = True
        state["patch_verification_decision"] = None
        state["patch_verification_approval_count"] = 0
        state["patch_verification"] = None
        state["runtime_tools_enabled"] = True
        source = Path("demo_app/app/api.py").read_bytes()
        saver = InMemorySaver()
        app = build_agent_graph(client, test_config(), checkpointer=saver)
        runtime = {"configurable": {"thread_id": "patch-verification-test"}}

        interrupted = app.invoke(state, config=runtime)

        self.assertIn("__interrupt__", interrupted)
        self.assertEqual(interrupted["patch_proposal"]["status"], "validated")
        request = interrupted["__interrupt__"][0].value
        self.assertEqual(request["reason"], "patch_verification")
        self.assertIn("api_missing_fields_contract", request["message"])
        verify_mock.assert_not_called()
        self.assertEqual(Path("demo_app/app/api.py").read_bytes(), source)
        self.assertNotIn("tools", client.fake_completions.requests[-1])
        patch_prompt = client.fake_completions.requests[-1]["messages"][1]["content"]
        self.assertIn("严格 JSON Schema", patch_prompt)
        self.assertIn("diagnosis_claim_ids", patch_prompt)
        self.assertIn("demo_missing_user_id", patch_prompt)
        self.assertIn("不得添加 type、patch_id、status", patch_prompt)

        verify_mock.return_value = PatchVerificationResult(
            proposal_id="patch-test",
            status="verified",
            applied_in_sandbox=True,
            required_check_ids=["api_missing_fields_contract"],
        )
        result = app.invoke(
            Command(resume={"action": "approve"}),
            config=runtime,
        )

        verify_mock.assert_called_once()
        self.assertEqual(result["patch_verification"]["status"], "verified")
        self.assertEqual(result["patch_verification_approval_count"], 1)
        self.assertEqual(Path("demo_app/app/api.py").read_bytes(), source)

    def test_tool_result_creates_observation_and_exposes_id(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":"main.py"}'},
            }]),
            classify_observations_message(["obs-001"]),
            FakeMessage(content=grounded_report()),
        ])
        result = build_agent_graph(client, test_config()).invoke(
            state_with_existing_hypothesis()
        )

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
            classify_observations_message(["obs-001"]),
            FakeMessage(content=grounded_report("obs-999")),
            FakeMessage(content=grounded_report("obs-001")),
        ])
        result = build_agent_graph(client, test_config()).invoke(
            state_with_existing_hypothesis()
        )

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
        result = app.invoke(state_with_existing_hypothesis())

        schema_names = {
            schema["function"]["name"]
            for schema in client.fake_completions.requests[0]["tools"]
        }
        self.assertEqual(
            schema_names,
            set(TOOL_PROFILES["code_only"]),
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
            classify_observations_message(["obs-001"]),
            FakeMessage(content=VALID_REPORT),
        ])
        app = build_agent_graph(client, test_config())
        result = app.invoke(state_with_existing_hypothesis())

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(result["step_count"], 3)
        self.assertEqual(result["tool_call_count"], 2)
        self.assertEqual(result["report"]["confidence"], "low")
        self.assertTrue(any(message.get("role") == "tool" for message in result["messages"]))

    def test_initial_hypothesis_gate_only_exposes_update_and_blocks_external_tool(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-external", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"main.py"}',
                },
            }]),
            FakeMessage(content=VALID_REPORT),
            FakeMessage(content=VALID_REPORT),
        ])

        result = build_agent_graph(client, test_config()).invoke(
            initial_state(max_steps=2)
        )

        self.assertEqual(
            [item["function"]["name"] for item in client.fake_completions.requests[0]["tools"]],
            ["update_hypotheses"],
        )
        self.assertFalse(result["observations"][0]["ok"])
        self.assertIn("尚未建立诊断假设", result["observations"][0]["error"])

    def test_initial_runtime_call_is_blocked_before_review(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-runtime-before-hypothesis", "type": "function",
                "function": {
                    "name": "run_demo_case",
                    "arguments": '{"case_id":"missing_user_id"}',
                },
            }]),
            FakeMessage(content=VALID_REPORT),
            FakeMessage(content=VALID_REPORT),
        ])
        state = initial_state(max_steps=2)
        state["human_review_enabled"] = True
        state["runtime_tools_enabled"] = True

        result = build_agent_graph(
            client,
            test_config(),
            allowed_tools=TOOL_PROFILES["full_runtime"],
            tool_profile="full_runtime",
        ).invoke(state)

        self.assertEqual(result["runtime_approval_count"], 0)
        self.assertEqual(result["runtime_call_count"], 0)
        self.assertIn("尚未建立诊断假设", result["observations"][0]["error"])

    def test_direct_report_after_new_observation_requires_classification(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-read", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"main.py"}',
                },
            }]),
            FakeMessage(content=VALID_REPORT),
            classify_observations_message(["obs-001"]),
            FakeMessage(content=VALID_REPORT),
        ])

        result = build_agent_graph(client, test_config()).invoke(
            state_with_existing_hypothesis()
        )

        self.assertEqual(result["stop_reason"], "completed")
        self.assertTrue(any(
            "最新成功 Observation 尚未归类" in error
            for error in result["validation_errors"]
        ))

    def test_invalid_report_is_retried(self):
        client = FakeClient([
            FakeMessage(content='{"summary":"字段不完整"}'),
            FakeMessage(content=VALID_REPORT),
        ])
        app = build_agent_graph(client, test_config())
        result = app.invoke(state_with_existing_hypothesis())

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
                    "arguments": {"path": "config.py"},
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
            classify_observations_message(
                ["obs-001", "obs-003"],
                call_id="call-final-classify",
                next_path="demo_app/app/api.py",
            ),
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
                "arguments": {"path": "main.py"},
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

    def test_initial_action_catalog_uses_current_profile_parameter_names(self):
        catalog = _next_action_catalog(TOOL_PROFILES["full"])

        self.assertIn("read_file(path, start_line?, end_line?)", catalog)
        self.assertIn("search_code(query", catalog)
        self.assertNotIn("list_checks", catalog)
        self.assertNotIn("file_path", catalog)

    def test_next_action_selection_treats_search_hit_as_not_yet_read(self):
        prior = ToolObservation(
            observation_id="obs-001",
            tool_call_id="call-search",
            step=1,
            tool_name="search_code",
            arguments={"query": "user_id"},
            ok=True,
            sources=[ObservedSource(
                source_type="code",
                file="demo_app/run_case.py",
                line_start=46,
                line_end=46,
            )],
            result_sha256="digest",
            result_excerpt="result",
            duration_ms=1,
        )
        root_cause = DiagnosticHypothesis(
            hypothesis_id="H1",
            statement="API 入口可能缺少校验",
            status="unverified",
            confidence=0.3,
            next_action={
                "tool_name": "search_code",
                "arguments": {"query": "def post_users"},
                "purpose": "定位新的入口来源",
                "supports_if": "入口直接透传",
                "rejects_if": "入口已校验",
            },
        )
        trigger = DiagnosticHypothesis(
            hypothesis_id="H2",
            statement="复现分支缺少字段",
            status="supported",
            confidence=0.7,
            supporting_observation_ids=["obs-001"],
            next_action={
                "tool_name": "read_file",
                "arguments": {
                    "path": "demo_app/run_case.py",
                    "start_line": 40,
                    "end_line": 60,
                },
                "purpose": "细看已知触发文件",
                "supports_if": "payload 缺字段",
                "rejects_if": "payload 完整",
            },
        )

        selected = _select_next_action([trigger, root_cause], [prior])

        self.assertIsNotNone(selected)
        self.assertEqual(selected[0].hypothesis_id, "H2")

    def test_hypothesis_update_without_new_evidence_must_advance_next_action(self):
        initial_hypotheses = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "API 入口可能缺少字段校验",
                "status": "unverified",
                "confidence": 0.5,
                "supporting_observation_ids": [],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "arguments": {"path": "demo_app/app/api.py"},
                    "purpose": "读取 API 入口确认是否校验字段",
                    "supports_if": "入口直接透传 payload",
                    "rejects_if": "入口已经返回 400",
                },
            }],
        })
        updated_hypotheses = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "API 入口缺少字段校验",
                "status": "supported",
                "confidence": 0.75,
                "supporting_observation_ids": ["obs-001"],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "arguments": {"path": "demo_app/app/service.py"},
                    "purpose": "读取 Service 交叉验证直接取键",
                    "supports_if": "Service 直接下标访问",
                    "rejects_if": "Service 有防御校验",
                },
            }],
        })
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-h1", "type": "function",
                "function": {
                    "name": "update_hypotheses",
                    "arguments": initial_hypotheses,
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-read", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"demo_app/app/api.py"}',
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-h2", "type": "function",
                "function": {
                    "name": "update_hypotheses",
                    "arguments": updated_hypotheses,
                },
            }]),
            FakeMessage(content=VALID_REPORT),
        ])

        result = build_agent_graph(client, test_config()).invoke(initial_state())
        second_request = client.fake_completions.requests[1]
        second_schema_names = {
            schema["function"]["name"] for schema in second_request["tools"]
        }

        self.assertNotIn("update_hypotheses", second_schema_names)
        self.assertTrue(any(
            "推进门" in message.get("content", "")
            and "demo_app/app/api.py" in message.get("content", "")
            and "read_file" in message.get("content", "")
            and "不得扩大读取范围" in message.get("content", "")
            for message in second_request["messages"]
        ))
        self.assertTrue(any(
            "demo_app/app/api.py" in signature
            for signature in result["tool_call_signatures"]
        ))

    def test_structured_next_action_rejects_expanded_read_range(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-wide", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": json.dumps({
                        "path": "demo_app/run_case.py",
                        "start_line": 1,
                        "end_line": 120,
                    }),
                },
            }]),
            FakeMessage(content=VALID_REPORT),
        ])
        state = initial_state()
        state["hypotheses"] = [{
            "hypothesis_id": "H1",
            "statement": "调用方传入了缺字段 payload",
            "status": "unverified",
            "confidence": 0.5,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "arguments": {
                    "path": "demo_app/run_case.py",
                    "start_line": 40,
                    "end_line": 60,
                },
                "purpose": "检查 missing_user_id 分支",
                "supports_if": "payload 缺少 user_id",
                "rejects_if": "payload 包含 user_id",
            },
        }]

        result = build_agent_graph(client, test_config()).invoke(state)

        self.assertEqual(result["observations"][0]["error"].split("；", 1)[0],
                         "工具调用与已校验的结构化 next_action 不一致")
        self.assertEqual(
            json.loads(result["messages"][3]["content"])["meta"]["reason"],
            "next_action_mismatch",
        )
        self.assertFalse(result["tool_call_signatures"])

    def test_undeclared_repeated_hypothesis_update_is_rejected(self):
        initial_hypotheses = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "API 入口可能缺少字段校验",
                "status": "unverified",
                "confidence": 0.5,
                "supporting_observation_ids": [],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "arguments": {"path": "demo_app/app/api.py"},
                    "purpose": "读取 API 入口确认是否校验字段",
                    "supports_if": "入口直接透传 payload",
                    "rejects_if": "入口已经返回 400",
                },
            }],
        })
        forbidden_update = json.dumps({
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": "没有新证据却提高置信度",
                "status": "supported",
                "confidence": 0.9,
                "supporting_observation_ids": [],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "arguments": {"path": "demo_app/app/api.py"},
                    "purpose": "仍应读取 API 入口",
                    "supports_if": "入口直接透传 payload",
                    "rejects_if": "入口已经返回 400",
                },
            }],
        })
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-h1", "type": "function",
                "function": {
                    "name": "update_hypotheses",
                    "arguments": initial_hypotheses,
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-illegal", "type": "function",
                "function": {
                    "name": "update_hypotheses",
                    "arguments": forbidden_update,
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-read", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"demo_app/app/api.py"}',
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-h2", "type": "function",
                "function": {
                    "name": "update_hypotheses",
                    "arguments": json.dumps({
                        "hypotheses": [{
                            "hypothesis_id": "H1",
                            "statement": "API 入口缺少字段校验",
                            "status": "supported",
                            "confidence": 0.75,
                            "supporting_observation_ids": ["obs-001"],
                            "contradicting_observation_ids": [],
                            "next_action": {
                                "tool_name": "read_file",
                                "arguments": {"path": "demo_app/app/service.py"},
                                "purpose": "读取 Service 交叉验证",
                                "supports_if": "Service 直接取键",
                                "rejects_if": "Service 已校验",
                            },
                        }],
                    }),
                },
            }]),
            FakeMessage(content=VALID_REPORT),
        ])

        result = build_agent_graph(client, test_config()).invoke(initial_state())

        self.assertTrue(any(
            "hypothesis_update_not_allowed" in message.get("content", "")
            for message in result["messages"]
            if message.get("role") == "tool"
        ))
        self.assertTrue(any(
            "demo_app/app/api.py" in signature
            for signature in result["tool_call_signatures"]
        ))

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

    def test_last_successful_observation_gets_one_classification_before_summary(self):
        initial_hypotheses = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "入口文件包含待确认行为",
            "status": "unverified",
            "confidence": 0.4,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "arguments": {"path": "main.py", "start_line": 1, "end_line": 3},
                "purpose": "读取入口前三行",
                "supports_if": "入口包含目标行为",
                "rejects_if": "入口不包含目标行为",
            },
        }]})
        classified_hypotheses = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "入口文件包含目标行为",
            "status": "confirmed",
            "confidence": 0.85,
            "supporting_observation_ids": ["obs-001"],
            "contradicting_observation_ids": [],
            "next_action": None,
        }]})
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-h1", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": initial_hypotheses},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-read", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"main.py","start_line":1,"end_line":3}',
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-h2", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": classified_hypotheses},
            }]),
            FakeMessage(content=grounded_report()),
        ])

        result = build_agent_graph(client, test_config()).invoke(initial_state(max_steps=2))

        self.assertTrue(result["final_classification_used"])
        self.assertEqual(result["step_count"], 2)
        self.assertEqual(result["hypotheses"][0]["status"], "confirmed")
        self.assertEqual(result["stop_reason"], "completed")
        classification_request = client.fake_completions.requests[2]
        self.assertEqual(
            [item["function"]["name"] for item in classification_request["tools"]],
            ["update_hypotheses"],
        )
        self.assertEqual(classification_request["tool_choice"], "auto")
        self.assertNotIn("tools", client.fake_completions.requests[3])

    def test_final_classification_accepts_supported_state_without_next_action(self):
        initial_hypotheses = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "API 入口行为待确认",
            "status": "unverified",
            "confidence": 0.4,
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "next_action": {
                "tool_name": "read_file",
                "arguments": {"path": "main.py", "start_line": 1, "end_line": 3},
                "purpose": "读取入口",
                "supports_if": "入口直接调用下游",
                "rejects_if": "入口已校验",
            },
        }]})
        terminal_update = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "API 入口直接调用下游",
            "status": "supported",
            "confidence": 0.75,
            "supporting_observation_ids": ["obs-001"],
            "contradicting_observation_ids": [],
            "next_action": None,
        }]})
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-h1", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": initial_hypotheses},
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-read", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"main.py","start_line":1,"end_line":3}',
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-final", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": terminal_update},
            }]),
            FakeMessage(content=grounded_report()),
        ])

        result = build_agent_graph(client, test_config()).invoke(
            initial_state(max_steps=2)
        )

        self.assertEqual(result["stop_reason"], "completed")
        self.assertTrue(result["final_classification_used"])
        self.assertEqual(result["hypotheses"][0]["status"], "supported")
        self.assertIsNone(result["hypotheses"][0]["next_action"])

    def test_initial_inline_hypothesis_object_avoids_retry_turn(self):
        initial = {
            "type": "hypotheses",
            "hypotheses": [{
                "hypothesis_id": "H1",
                "statement": 'API 入口可能读取 mapping["required_key"]',
                "status": "unverified",
                "confidence": 0.4,
                "supporting_observation_ids": [],
                "contradicting_observation_ids": [],
                "next_action": {
                    "tool_name": "read_file",
                    "arguments": {
                        "path": "main.py", "start_line": 1, "end_line": 3,
                    },
                    "purpose": "读取入口",
                    "supports_if": "入口直接调用下游",
                    "rejects_if": "入口已校验",
                },
            }],
        }
        terminal = json.dumps({"hypotheses": [{
            "hypothesis_id": "H1",
            "statement": "API 入口直接调用下游",
            "status": "supported",
            "confidence": 0.75,
            "supporting_observation_ids": ["obs-001"],
            "contradicting_observation_ids": [],
            "next_action": None,
        }]})
        malformed_inline = json.dumps(initial, ensure_ascii=False).replace(
            'mapping[\\"required_key\\"]',
            'mapping["required_key"]',
        )
        client = FakeClient([
            FakeMessage(content=malformed_inline),
            FakeMessage(tool_calls=[{
                "id": "call-read", "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"main.py","start_line":1,"end_line":3}',
                },
            }]),
            FakeMessage(tool_calls=[{
                "id": "call-final", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": terminal},
            }]),
            FakeMessage(content=grounded_report()),
        ])

        result = build_agent_graph(client, test_config()).invoke(
            initial_state(max_steps=2)
        )

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(result["step_count"], 2)
        self.assertEqual(result["model_call_count"], 4)
        self.assertEqual(result["hypotheses"][0]["status"], "supported")
        self.assertFalse(any(
            "调查尚未建立初始诊断假设" in item
            for item in result["validation_errors"]
        ))

    def test_missing_user_id_fake_flow_reaches_grounded_root_cause(self):
        def hypothesis_update(status, confidence, supporting, action):
            return json.dumps({"hypotheses": [{
                "hypothesis_id": "H1",
                "statement": (
                    "API 入口缺少 user_id 校验，非法 payload 进入 Service，"
                    "随后读取 payload[\"user_id\"] 触发 KeyError"
                ),
                "status": status,
                "confidence": confidence,
                "supporting_observation_ids": supporting,
                "contradicting_observation_ids": [],
                "next_action": action,
            }]})

        search_action = {
            "tool_name": "search_code",
            "arguments": {"query": "missing_user_id"},
            "purpose": "定位复现场景入口",
            "supports_if": "存在对应 case 分支",
            "rejects_if": "不存在对应分支",
        }
        run_case_action = {
            "tool_name": "read_file",
            "arguments": {
                "path": "demo_app/run_case.py", "start_line": 40, "end_line": 60,
            },
            "purpose": "读取复现分支传入的 payload",
            "supports_if": "payload 缺少 user_id",
            "rejects_if": "payload 包含 user_id",
        }
        api_action = {
            "tool_name": "read_file",
            "arguments": {
                "path": "demo_app/app/api.py", "start_line": 1, "end_line": 15,
            },
            "purpose": "检查 API 边界校验",
            "supports_if": "API 直接透传 payload",
            "rejects_if": "API 拒绝缺少字段的请求",
        }
        service_action = {
            "tool_name": "read_file",
            "arguments": {
                "path": "demo_app/app/service.py", "start_line": 1, "end_line": 15,
            },
            "purpose": "确认 Service 的实际抛错点",
            "supports_if": "Service 使用 payload 下标访问 user_id",
            "rejects_if": "Service 已安全处理缺失字段",
        }
        report = json.dumps({
            "summary": "缺少入口校验的 payload 在 Service 中触发 KeyError",
            "root_cause": (
                "API 入口没有校验必填 user_id，missing_user_id 分支把非法 payload 传入 "
                "Service，Service 随后以 payload[\"user_id\"] 取值并触发 KeyError。"
            ),
            "claims": [{
                "claim_id": "C1",
                "statement": "调用方构造了缺少 user_id 的 payload，API 未校验即传入 Service",
                "evidence_ids": ["E1", "E2", "E3"],
            }],
            "evidence": [{
                "evidence_id": "E1", "observation_id": "obs-002",
                "source_type": "code", "file": "demo_app/run_case.py",
                "line_start": 46, "line_end": 47, "commit_hash": None,
                "runtime_id": None, "description": "复现分支传入缺少 user_id 的 payload",
            }, {
                "evidence_id": "E2", "observation_id": "obs-003",
                "source_type": "code", "file": "demo_app/app/api.py",
                "line_start": 8, "line_end": 10, "commit_hash": None,
                "runtime_id": None, "description": "API 未校验 payload 即调用 Service",
            }, {
                "evidence_id": "E3", "observation_id": "obs-004",
                "source_type": "code", "file": "demo_app/app/service.py",
                "line_start": 8, "line_end": 10, "commit_hash": None,
                "runtime_id": None, "description": "Service 直接下标访问 user_id",
            }],
            "suggested_fixes": ["在 API 边界校验 user_id 并按接口契约返回客户端错误"],
            "confidence": "high",
        })
        initial_inline = json.loads(hypothesis_update(
            "unverified", 0.35, [], search_action,
        ))
        initial_inline["type"] = "hypotheses"
        malformed_initial_inline = json.dumps(
            initial_inline, ensure_ascii=False
        ).replace(
            'payload[\\"user_id\\"]',
            'payload["user_id"]',
        )
        client = FakeClient([
            FakeMessage(content=malformed_initial_inline),
            FakeMessage(tool_calls=[{
                "id": "search", "type": "function",
                "function": {"name": "search_code", "arguments": '{"query":"missing_user_id"}'},
            }]),
            FakeMessage(tool_calls=[{
                "id": "h2", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": hypothesis_update(
                    "unverified", 0.45, ["obs-001"], run_case_action,
                )},
            }]),
            FakeMessage(tool_calls=[{
                "id": "run-case", "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps(run_case_action["arguments"])},
            }]),
            FakeMessage(tool_calls=[{
                "id": "h3", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": hypothesis_update(
                    "supported", 0.65, ["obs-001", "obs-002"], api_action,
                )},
            }]),
            FakeMessage(tool_calls=[{
                "id": "api", "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps(api_action["arguments"])},
            }]),
            FakeMessage(tool_calls=[{
                "id": "h4", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": hypothesis_update(
                    "supported", 0.78, ["obs-001", "obs-002", "obs-003"], service_action,
                )},
            }]),
            FakeMessage(tool_calls=[{
                "id": "service", "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps(service_action["arguments"])},
            }]),
            FakeMessage(tool_calls=[{
                "id": "h5", "type": "function",
                "function": {"name": "update_hypotheses", "arguments": hypothesis_update(
                    "confirmed", 0.92, ["obs-002", "obs-003", "obs-004"], None,
                )},
            }]),
            FakeMessage(content=report),
        ])

        result = build_agent_graph(client, test_config()).invoke(initial_state(max_steps=8))

        self.assertEqual(result["stop_reason"], "completed")
        self.assertEqual(result["report"]["confidence"], "high")
        self.assertIn("payload[\"user_id\"]", result["report"]["root_cause"])
        self.assertEqual(result["hypotheses"][0]["status"], "confirmed")
        self.assertTrue(result["final_classification_used"])
        self.assertFalse(result["repair_attempted"])
        self.assertEqual(result["repeated_tool_call_count"], 0)
        self.assertTrue(any('"start_line":40' in item for item in result["tool_call_signatures"]))

    def test_first_duplicate_tool_call_allows_one_correction_turn(self):
        repeated_call = {
            "id": "call-2",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path":"missing-file.py"}',
            },
        }
        client = FakeClient([
            FakeMessage(tool_calls=[{**repeated_call, "id": "call-1"}]),
            FakeMessage(tool_calls=[repeated_call]),
            FakeMessage(content=VALID_REPORT),
        ])
        app = build_agent_graph(client, test_config())
        result = app.invoke(state_with_existing_hypothesis())

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
                    "name": "read_file",
                    "arguments": '{"path":"missing-file.py"}',
                },
            }

        client = FakeClient([
            FakeMessage(tool_calls=[repeated_call("call-1")]),
            FakeMessage(tool_calls=[repeated_call("call-2")]),
            FakeMessage(tool_calls=[repeated_call("call-3")]),
            FakeMessage(content=VALID_REPORT),
        ])
        result = build_agent_graph(client, test_config()).invoke(
            state_with_existing_hypothesis()
        )

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
        repair_prompt = client.fake_completions.requests[-1]["messages"][-1]["content"]
        self.assertIn("suggested_fixes 必须是字符串数组", repair_prompt)
        self.assertIn("Claim.evidence_ids", repair_prompt)

    def test_local_json_repair_completes_without_extra_model_call(self):
        payload = json.loads(VALID_REPORT)
        payload["root_cause"] = 'Service 使用 payload["user_id"] 触发 KeyError'
        malformed = json.dumps(payload, ensure_ascii=False).replace(
            'payload[\\"user_id\\"]',
            'payload["user_id"]',
        )
        client = FakeClient([FakeMessage(content=malformed)])
        state = state_with_existing_hypothesis(max_steps=1)
        state["max_model_calls"] = 1

        result = build_agent_graph(client, test_config()).invoke(state)

        self.assertEqual(result["stop_reason"], "completed")
        self.assertTrue(result["repair_attempted"])
        self.assertEqual(result["model_call_count"], 1)
        self.assertEqual(len(client.fake_completions.requests), 1)

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
                "arguments": {"path": "config.py"},
                "purpose": "读取另一配置文件交叉验证",
                "supports_if": "配置不一致",
                "rejects_if": "配置一致",
            },
        }]
        state["patch_requested"] = True

        result = build_agent_graph(client, test_config()).invoke(state)

        self.assertEqual(result["stop_reason"], "invalid_synthesis")
        self.assertEqual(result["report"]["root_cause"], "入口配置存在错误")
        self.assertEqual(result["report"]["confidence"], "medium")
        self.assertEqual(result["report"]["evidence"][0]["observation_id"], "obs-001")
        self.assertEqual(len(result["validation_errors"]), 3)
        self.assertTrue(result["patch_attempted"])
        self.assertIn("Patch Proposal 已跳过", result["patch_validation_errors"][0])

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
            }, {
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
            state_with_existing_hypothesis()
        )

        self.assertTrue(result["early_stopped"])
        self.assertTrue(result["synthesis_attempted"])
        self.assertEqual(result["hypotheses"][0]["status"], "confirmed")
        self.assertEqual(result["step_count"], 2)
        synthesis_prompt = client.fake_completions.requests[-1]["messages"][-1]["content"]
        self.assertIn("严格 JSON Schema", synthesis_prompt)

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
            }, {
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
            state_with_existing_hypothesis(max_steps=2)
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
        state = state_with_existing_hypothesis()
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

    def test_runtime_execution_interrupts_before_running_and_can_be_approved(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-runtime", "type": "function",
                "function": {
                    "name": "run_demo_case",
                    "arguments": '{"case_id":"missing_user_id"}',
                },
            }]),
            classify_observations_message(
                ["obs-001"], next_path="demo_app/app/api.py"
            ),
            FakeMessage(content=VALID_REPORT),
        ])
        saver = InMemorySaver()
        app = build_agent_graph(
            client,
            test_config(),
            checkpointer=saver,
            allowed_tools=TOOL_PROFILES["full_runtime"],
            tool_profile="full_runtime",
        )
        state = state_with_existing_hypothesis()
        state["human_review_enabled"] = True
        state["runtime_tools_enabled"] = True
        runtime = {"configurable": {"thread_id": "runtime-approval-test"}}

        interrupted = app.invoke(state, config=runtime)
        self.assertIn("__interrupt__", interrupted)
        self.assertEqual(interrupted["runtime_call_count"], 0)
        self.assertEqual(interrupted["observations"], [])

        resumed = app.invoke(
            Command(resume={"action": "approve"}),
            config=runtime,
        )
        self.assertEqual(resumed["stop_reason"], "completed")
        self.assertEqual(resumed["runtime_call_count"], 1)
        self.assertEqual(resumed["successful_runtime_call_count"], 1)
        self.assertEqual(resumed["runtime_approval_count"], 1)
        source = resumed["observations"][0]["sources"][0]
        self.assertEqual(source["source_type"], "runtime")
        self.assertTrue(source["runtime_id"].startswith("runtime-missing_user_id-"))

    def test_runtime_execution_denial_creates_failure_without_running(self):
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-runtime", "type": "function",
                "function": {
                    "name": "run_demo_case",
                    "arguments": '{"case_id":"schema_mismatch"}',
                },
            }]),
            FakeMessage(content=VALID_REPORT),
        ])
        saver = InMemorySaver()
        app = build_agent_graph(
            client,
            test_config(),
            checkpointer=saver,
            allowed_tools=TOOL_PROFILES["full_runtime"],
            tool_profile="full_runtime",
        )
        state = state_with_existing_hypothesis()
        state["human_review_enabled"] = True
        state["runtime_tools_enabled"] = True
        runtime = {"configurable": {"thread_id": "runtime-denial-test"}}

        app.invoke(state, config=runtime)
        resumed = app.invoke(
            Command(resume={"action": "deny"}),
            config=runtime,
        )

        self.assertEqual(resumed["runtime_call_count"], 0)
        self.assertEqual(resumed["runtime_denial_count"], 1)
        self.assertFalse(resumed["observations"][0]["ok"])
        self.assertIn("用户拒绝", resumed["observations"][0]["error"])

    @patch("harness.subprocess.run")
    def test_harness_check_interrupts_and_resumes_through_runtime_gate(
        self, run_mock
    ):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["python"],
            returncode=1,
            stdout="",
            stderr="KeyError: 'user_id'",
        )
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-harness", "type": "function",
                "function": {
                    "name": "run_check",
                    "arguments": '{"check_id":"demo_missing_user_id"}',
                },
            }]),
            classify_observations_message(
                ["obs-001"], next_path="demo_app/app/api.py"
            ),
            FakeMessage(content=VALID_REPORT),
        ])
        saver = InMemorySaver()
        app = build_agent_graph(
            client,
            test_config(),
            checkpointer=saver,
            allowed_tools=TOOL_PROFILES["full_runtime"],
            tool_profile="full_runtime",
        )
        state = state_with_existing_hypothesis()
        state["human_review_enabled"] = True
        state["runtime_tools_enabled"] = True
        runtime = {"configurable": {"thread_id": "harness-approval-test"}}

        interrupted = app.invoke(state, config=runtime)
        self.assertIn("__interrupt__", interrupted)
        request = interrupted["__interrupt__"][0].value
        self.assertIn("run_check(demo_missing_user_id)", request["message"])
        resumed = app.invoke(
            Command(resume={"action": "approve"}),
            config=runtime,
        )

        self.assertEqual(resumed["runtime_call_count"], 1)
        self.assertEqual(resumed["successful_runtime_call_count"], 1)
        self.assertEqual(resumed["observations"][0]["tool_name"], "run_check")
        self.assertEqual(
            resumed["observations"][0]["sources"][0]["source_type"], "runtime"
        )

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
        state = state_with_existing_hypothesis()
        state["max_tool_calls"] = 1
        state["final_classification_used"] = True

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
                    "arguments": {"path": ".", "max_depth": 1},
                    "purpose": "定位入口文件",
                    "supports_if": "存在入口文件",
                    "rejects_if": "不存在入口文件",
                },
            }],
        })
        client = FakeClient([
            FakeMessage(tool_calls=[{
                "id": "call-h", "type": "function",
                "function": {
                    "name": "update_hypotheses",
                    "arguments": hypothesis_arguments,
                },
            }]),
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
            classify_observations_message(
                ["obs-001"], next_path="demo_app/app/api.py"
            ),
            FakeMessage(content=VALID_REPORT),
        ])
        state = initial_state()
        state["max_tools_per_step"] = 1

        result = build_agent_graph(client, test_config()).invoke(state)

        self.assertFalse(result["force_synthesis"])
        self.assertEqual(result["step_count"], 4)
        self.assertEqual(result["tool_call_count"], 4)
        self.assertEqual(len(result["observations"]), 2)
        self.assertTrue(result["observations"][0]["ok"])
        self.assertIn("单轮最多执行 1 个工具", result["observations"][1]["error"])


if __name__ == "__main__":
    unittest.main()
