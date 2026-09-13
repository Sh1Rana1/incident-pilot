"""IncidentPilot V11 假设驱动、Safe Test Harness 与来源验证图。"""

import json
import hashlib
import operator
from time import perf_counter
from typing import Annotated, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from openai import OpenAI
from pydantic import ValidationError
from typing_extensions import TypedDict

from config import AppConfig
from context_manager import compact_messages
from hypotheses import (
    HYPOTHESIS_TOOL_NAME,
    evidence_is_sufficient,
    hypotheses_conflict,
    hypothesis_tool_schema,
    parse_hypothesis_update,
    validate_hypothesis_readiness,
)
from models import (
    DiagnosticClaim,
    DiagnosticHypothesis,
    Evidence,
    HumanReviewRequest,
    IncidentReport,
    ToolResult,
    ToolObservation,
)
from provenance import build_observation, validate_report_provenance
from registry import registry
from runtime_tools import (
    activate_runtime_execution,
    activate_runtime_timeout,
    reset_runtime_execution,
    reset_runtime_timeout,
)
from tool_profiles import RUNTIME_EXECUTION_TOOLS
import harness  # noqa: F401：导入时注册 V11 Harness 工具
import tools  # noqa: F401：导入时触发工具注册


SYSTEM_PROMPT = """你是 IncidentPilot，一个假设驱动、证据驱动的代码故障分析 Agent。
你的任务是根据用户给出的报错，在当前项目中搜索和读取代码，找到根因。
先提出 2–4 个可证伪的候选根因，并调用 update_hypotheses 保存；再选择最能区分候选假设、成本最低的工具，不要无目的遍历项目。
未确认假设的 next_action 必须包含 tool_name、purpose、supports_if、rejects_if，只规划一个最有信息增益的下一动作。
获得新证据后调用 update_hypotheses 更新完整假设集合：支持、反证、置信度和下一步动作都要来自真实 Observation。
只要上一轮产生了新的成功 Observation，下一轮必须先成功调用 update_hypotheses；完成更新前不要继续调用外部工具。
不要预猜尚未返回的 Observation ID；必须等工具结果出现后，再在后续响应中引用。
每轮最多选择三个工具；traceback 已给文件时优先直接读取，已知符号时优先搜索，供应商契约问题优先文档；没有回归线索不要调用 Git。
当用户明确要求复现故障或需要运行时证据时，先用静态证据缩小范围。优先调用 list_checks 查看项目所有者预登记的测试，再调用 run_check(check_id)；兼容工具 run_demo_case 仍可复现四个固定案例。这些工具都不能接受 Shell 命令。
run_check/run_demo_case 返回的 exception_message、failed_tests 和 traceback_frames 是真实运行结果：优先读取其中的项目业务文件，并用精确错误码、配置键检索文档；RuntimeError 是 Python 异常类型，不代表其中的 HTTP 错误文本是伪造的。
当某个假设已由至少两项独立来源确认时，应停止扩散调查并输出最终报告。
不要猜测；不要声称看过没有读取的文件。
每个工具结果的 meta.observation_id 是系统生成的真实来源编号。
最终只能输出 JSON，字段必须是 summary、root_cause、claims、evidence、suggested_fixes、confidence。
claims 每项包含 claim_id、statement、evidence_ids；每个 medium/high 结论都必须绑定证据。
evidence 每项必须包含 evidence_id、observation_id、source_type、file、line_start、line_end、
commit_hash、runtime_id、description。代码、文档和日志证据的文件与行号必须真实出现在对应 Observation；
Git 提交证据填写 commit_hash，file 填空字符串，line_start/line_end 填 null。
Runtime 证据填写 runtime_id，file 填空字符串，line_start/line_end 和 commit_hash 填 null。
不要把无法确认的信息、目录、unknown、N/A 或自然语言说明伪装成文件证据。
source_type 只能是 code、documentation、git、runtime、unknown；confidence 只能是
low、medium、high。如果证据不足，只保留已验证的 Evidence，降低 confidence 并明确缺口。
你只能调查和提出建议，不能修改文件。"""


class AgentState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    step_count: int
    tool_call_count: int
    max_steps: int
    report: Optional[dict]
    validation_error: Optional[str]
    validation_errors: Annotated[list[str], operator.add]
    stop_reason: Optional[str]
    tool_call_signatures: list[str]
    repeated_tool_call_count: int
    force_synthesis: bool
    synthesis_attempted: bool
    repair_attempted: bool
    observations: Annotated[list[dict], operator.add]
    hypotheses: list[dict]
    model_call_count: int
    input_token_count: int
    output_token_count: int
    total_token_count: int
    max_model_calls: int
    max_tool_calls: int
    evidence_sufficient: bool
    early_stopped: bool
    human_review_enabled: bool
    human_review_triggered: bool
    human_review_count: int
    pending_review_reason: Optional[str]
    hitl_model_threshold: int
    hitl_tool_threshold: int
    cancelled: bool
    max_tools_per_step: int
    context_compaction_count: int
    confirmed_at_tool_call_count: Optional[int]
    hypothesis_update_required: bool
    runtime_tools_enabled: bool
    runtime_execution_preapproved: bool
    runtime_execution_decision: Optional[str]
    runtime_call_count: int
    successful_runtime_call_count: int
    runtime_timeout_count: int
    runtime_approval_count: int
    runtime_denial_count: int
    max_runtime_calls: int
    runtime_replay_count: int
    runtime_ledger_path: Optional[str]
    thread_id: str
    recalled_memory_count: int


def response_format(config: AppConfig):
    if config.output_mode == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "incident_report",
                "strict": True,
                "schema": IncidentReport.model_json_schema(),
            },
        }
    if config.output_mode == "json_object":
        return {"type": "json_object"}
    return None


def assistant_message_to_dict(message) -> dict:
    """把 SDK 对象转换为可 checkpoint 的普通字典。"""
    data = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else dict(message)
    data["role"] = "assistant"
    return data


def response_usage(response) -> tuple[int, int, int]:
    """兼容 OpenAI 与兼容服务缺失 usage 的响应。"""
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0, 0
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or prompt + completion)
        return prompt, completion, total
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or prompt + completion)
    return prompt, completion, total


def _model_usage_update(state: AgentState, response) -> dict:
    prompt, completion, total = response_usage(response)
    return {
        "model_call_count": state.get("model_call_count", 0) + 1,
        "input_token_count": state.get("input_token_count", 0) + prompt,
        "output_token_count": state.get("output_token_count", 0) + completion,
        "total_token_count": state.get("total_token_count", 0) + total,
    }


def route_after_model(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if last_message.get("tool_calls"):
        requests_runtime = any(
            call.get("function", {}).get("name") in RUNTIME_EXECUTION_TOOLS
            for call in last_message["tool_calls"]
        )
        if (
            requests_runtime
            and state.get("runtime_tools_enabled")
            and state.get("human_review_enabled")
            and not state.get("runtime_execution_preapproved")
            and state.get("runtime_execution_decision") is None
        ):
            return "runtime_review"
        return "execute_tools"
    return "validate_report"


def route_after_validation(state: AgentState) -> str:
    if state.get("report") is not None:
        return "end"
    if state.get("synthesis_attempted"):
        if state.get("repair_attempted"):
            return "build_fallback"
        return "repair_report"
    if (
        state["step_count"] >= state["max_steps"]
        or state.get("model_call_count", 0) >= max(
            1, state.get("max_model_calls", 10) - 2
        )
    ):
        return "synthesize_report"
    return "call_model"


def route_after_tools(state: AgentState) -> str:
    """工具执行后决定继续调查，还是用已有证据强制收尾。"""
    if state.get("cancelled"):
        return "build_cancelled"
    if state.get("force_synthesis") or state["step_count"] >= state["max_steps"]:
        return "synthesize_report"
    if state.get("pending_review_reason"):
        return "human_review"
    if state.get("evidence_sufficient"):
        return "synthesize_report"
    if state.get("model_call_count", 0) >= max(
        1, state.get("max_model_calls", 10) - 2
    ):
        return "synthesize_report"
    return "call_model"


def route_after_human_review(state: AgentState) -> str:
    if state.get("cancelled"):
        return "build_cancelled"
    if state.get("force_synthesis"):
        return "synthesize_report"
    return "call_model"


def route_after_runtime_review(state: AgentState) -> str:
    if state.get("cancelled"):
        return "build_cancelled"
    return "execute_tools"


def tool_call_signature(name: str, arguments: str) -> str:
    """将参数规范化，识别 JSON 键顺序不同但语义相同的重复调用。"""
    try:
        normalized_arguments = json.dumps(
            json.loads(arguments), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (json.JSONDecodeError, TypeError):
        normalized_arguments = str(arguments).strip()
    return f"{name}:{normalized_arguments}"


def parse_incident_report(content: str) -> IncidentReport:
    """兼容纯 JSON、Markdown 代码块和 JSON 前后少量说明文字。"""
    stripped = content.strip()
    candidates = [stripped]
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            candidates.append("\n".join(lines[1:-1]).strip())
    start, end = stripped.find("{"), stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start:end + 1])

    last_error: ValidationError | None = None
    for candidate in dict.fromkeys(candidates):
        try:
            return IncidentReport.model_validate_json(candidate)
        except ValidationError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def format_report_validation_error(exc: ValidationError) -> str:
    """保留可操作的字段路径与原因，供修复节点和评测 JSON 审计。"""
    details = []
    for item in exc.errors(include_url=False)[:8]:
        location = ".".join(str(part) for part in item.get("loc", ())) or "report"
        details.append(f"{location}: {item.get('msg', 'invalid value')}")
    suffix = "；其余错误已省略" if exc.error_count() > len(details) else ""
    return f"最终报告有 {exc.error_count()} 处格式错误：" + "；".join(details) + suffix


def build_agent_graph(
    client: OpenAI,
    config: AppConfig,
    checkpointer=None,
    allowed_tools: frozenset[str] | set[str] | None = None,
    tool_profile: str | None = None,
):
    """使用依赖注入构建图，便于真实运行和模拟测试。"""

    def request_messages(
        state: AgentState,
        *,
        include_last_assistant: bool = False,
        final_report: bool = False,
    ) -> tuple[list[dict], bool]:
        messages, compacted = compact_messages(
            state["messages"],
            [
                ToolObservation.model_validate(item)
                for item in state.get("observations", [])
            ],
            [
                DiagnosticHypothesis.model_validate(item)
                for item in state.get("hypotheses", [])
            ],
            state.get("validation_error"),
            include_last_assistant=include_last_assistant,
            final_report=final_report,
        )
        if state.get("hypothesis_update_required") and not final_report:
            messages = messages + [{
                "role": "system",
                "content": (
                    "控制门：上一轮产生了新的成功 Observation。本轮必须先调用且成功完成 "
                    "update_hypotheses，把新证据归入支持、反证或说明暂不相关；在此之前"
                    "不要调用任何外部工具。"
                ),
            }]
        return messages, compacted

    def call_model(state: AgentState) -> dict:
        step = state["step_count"] + 1
        print(f"\n--- Agent 第 {step} 步 ---")
        tool_schemas = registry.schemas(
            strict=config.strict_tools,
            allowed_tools=allowed_tools,
        )
        tool_schemas.append(hypothesis_tool_schema())
        messages, compacted = request_messages(state)
        request = {
            "model": config.model,
            "messages": messages,
            "tools": tool_schemas,
            "tool_choice": "auto",
        }
        output_format = response_format(config)
        if output_format is not None:
            request["response_format"] = output_format
        response = client.chat.completions.create(**request)
        return {
            "messages": [assistant_message_to_dict(response.choices[0].message)],
            "step_count": step,
            "validation_error": None,
            "context_compaction_count": (
                state.get("context_compaction_count", 0) + int(compacted)
            ),
            **_model_usage_update(state, response),
        }

    def runtime_review(state: AgentState) -> dict:
        """在任何运行时工具实际执行前，用 Checkpoint 暂停并取得单次授权。"""
        requested_items: list[str] = []
        for call in state["messages"][-1].get("tool_calls", []):
            name = call.get("function", {}).get("name")
            if name not in RUNTIME_EXECUTION_TOOLS:
                continue
            try:
                payload = json.loads(call["function"].get("arguments", "{}"))
                identifier = payload.get("check_id") or payload.get("case_id")
                requested_items.append(f"{name}({identifier or 'unknown'})")
            except (json.JSONDecodeError, TypeError):
                requested_items.append(f"{name}(invalid)")
        request = HumanReviewRequest(
            reason="runtime_execution",
            message=(
                "Agent 请求运行预登记检查："
                + ", ".join(requested_items)
                + "。本次授权只适用于当前工具调用，不允许任意命令。"
            ),
            model_call_count=state.get("model_call_count", 0),
            tool_call_count=state.get("tool_call_count", 0),
            hypotheses=[
                DiagnosticHypothesis.model_validate(item)
                for item in state.get("hypotheses", [])
            ],
            allowed_actions=["approve", "deny", "cancel"],
        )
        decision = interrupt(request.model_dump(mode="json"))
        action = (
            str(decision.get("action", "deny")).lower()
            if isinstance(decision, dict)
            else str(decision).lower()
        )
        if action not in {"approve", "deny", "cancel"}:
            action = "deny"
        return {
            "runtime_execution_decision": action,
            "runtime_approval_count": (
                state.get("runtime_approval_count", 0) + int(action == "approve")
            ),
            "runtime_denial_count": (
                state.get("runtime_denial_count", 0) + int(action == "deny")
            ),
            "human_review_count": state.get("human_review_count", 0) + 1,
            "cancelled": action == "cancel",
        }

    def execute_tools(state: AgentState) -> dict:
        tool_messages: list[dict] = []
        observations: list[dict] = []
        calls = state["messages"][-1].get("tool_calls", [])
        known_signatures = set(state.get("tool_call_signatures", []))
        new_signatures: list[str] = []
        repeated_count = 0
        current_hypotheses = [
            DiagnosticHypothesis.model_validate(item)
            for item in state.get("hypotheses", [])
        ]
        existing_observations = [
            ToolObservation.model_validate(item)
            for item in state.get("observations", [])
        ]
        remaining_budget = max(
            0,
            state.get("max_tool_calls", config.max_tool_calls)
            - state.get("tool_call_count", 0),
        )
        per_step_limit = state.get("max_tools_per_step", config.max_tools_per_step)
        executed_external_count = 0
        hypothesis_update_required = state.get("hypothesis_update_required", False)
        new_successful_observation = False
        protected_access_attempted = False
        runtime_call_count = state.get("runtime_call_count", 0)
        successful_runtime_call_count = state.get("successful_runtime_call_count", 0)
        runtime_timeout_count = state.get("runtime_timeout_count", 0)
        runtime_replay_count = state.get("runtime_replay_count", 0)
        for call_index, tool_call in enumerate(calls):
            function = tool_call["function"]
            name, arguments = function["name"], function["arguments"]
            total_budget_exhausted = call_index >= remaining_budget
            per_step_exhausted = (
                name != HYPOTHESIS_TOOL_NAME
                and executed_external_count >= per_step_limit
            )
            update_missing = (
                name != HYPOTHESIS_TOOL_NAME and hypothesis_update_required
            )
            if total_budget_exhausted or per_step_exhausted or update_missing:
                reason = (
                    "tool_budget_exhausted"
                    if total_budget_exhausted
                    else (
                        "per_step_tool_limit"
                        if per_step_exhausted
                        else "hypothesis_update_required"
                    )
                )
                error = (
                    "工具调用预算已经用完，请根据已有证据生成报告。"
                    if total_budget_exhausted
                    else (
                        f"单轮最多执行 {per_step_limit} 个工具，请按信息增益排序后在下一轮继续。"
                        if per_step_exhausted
                        else "上一轮的新证据尚未写入假设；请先单独调用 update_hypotheses，再继续调查。"
                    )
                )
                result = json.dumps({
                    "ok": False,
                    "error": error,
                    "meta": {"reason": reason},
                }, ensure_ascii=False)
                if name != HYPOTHESIS_TOOL_NAME:
                    observation_id = (
                        f"obs-{len(state.get('observations', [])) + len(observations) + 1:03d}"
                    )
                    observation, result = build_observation(
                        observation_id=observation_id,
                        tool_call_id=tool_call["id"],
                        step=state["step_count"],
                        tool_name=name,
                        arguments_json=arguments,
                        result_json=result,
                        duration_ms=0.0,
                        repeated=False,
                    )
                    observations.append(observation.model_dump(mode="json"))
                print(f"跳过受限工具调用: {name}({arguments})")
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                })
                continue

            if name == HYPOTHESIS_TOOL_NAME:
                parsed, result = parse_hypothesis_update(
                    arguments,
                    existing_observations + [
                        ToolObservation.model_validate(item) for item in observations
                    ],
                )
                if parsed is not None:
                    current_hypotheses = parsed
                    hypothesis_update_required = False
                    print(
                        "更新诊断假设: "
                        + ", ".join(
                            f"{item.hypothesis_id}={item.status}({item.confidence:.0%})"
                            for item in parsed
                        )
                    )
                else:
                    print(f"假设更新失败: {result[:500]}")
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                })
                continue

            executed_external_count += 1
            signature = tool_call_signature(name, arguments)
            observation_id = f"obs-{len(state.get('observations', [])) + len(observations) + 1:03d}"
            started_at = perf_counter()
            repeated = False
            if signature in known_signatures:
                repeated_count += 1
                repeated = True
                result = json.dumps({
                    "ok": False,
                    "error": "相同工具和参数已经调用过，请使用已有结果并生成最终报告。",
                    "meta": {"reason": "duplicate_tool_call"},
                }, ensure_ascii=False)
                print(f"跳过重复工具调用: {name}({arguments})")
            else:
                runtime_block_reason: str | None = None
                if name in RUNTIME_EXECUTION_TOOLS:
                    if state.get("runtime_execution_decision") == "deny":
                        runtime_block_reason = "用户拒绝了本次运行时执行。"
                    elif not (
                        state.get("runtime_execution_preapproved")
                        or state.get("runtime_execution_decision") == "approve"
                    ):
                        runtime_block_reason = "运行时工具尚未获得明确授权。"
                    elif runtime_call_count >= state.get("max_runtime_calls", 1):
                        runtime_block_reason = "运行时调用预算已经用完。"
                if runtime_block_reason is not None:
                    result = ToolResult.failure(
                        runtime_block_reason,
                        tool=name,
                        reason="runtime_not_authorized",
                    ).model_dump_json()
                    print(f"跳过运行时工具: {name}({arguments})")
                else:
                    print(f"调用工具: {name}({arguments})")
                    timeout_token = activate_runtime_timeout(
                        config.runtime_timeout_seconds
                    )
                    execution_token = None
                    if name in RUNTIME_EXECUTION_TOOLS and state.get("runtime_ledger_path"):
                        execution_id = hashlib.sha256(
                            f"{state.get('thread_id', '')}:{tool_call['id']}".encode("utf-8")
                        ).hexdigest()[:24]
                        execution_token = activate_runtime_execution(
                            execution_id,
                            state["runtime_ledger_path"],
                        )
                    try:
                        result = registry.execute(
                            name,
                            arguments,
                            allowed_tools=allowed_tools,
                            tool_profile=tool_profile,
                        )
                    finally:
                        if execution_token is not None:
                            reset_runtime_execution(execution_token)
                        reset_runtime_timeout(timeout_token)
                    print(f"工具结果: {result[:500]}")
                    if name in RUNTIME_EXECUTION_TOOLS:
                        runtime_call_count += 1
                        runtime_payload = json.loads(result)
                        if (runtime_payload.get("meta") or {}).get("replayed"):
                            runtime_replay_count += 1
                        if runtime_payload.get("ok"):
                            successful_runtime_call_count += 1
                        elif (runtime_payload.get("meta") or {}).get("timed_out"):
                            runtime_timeout_count += 1
                    if "属于评测或内部缓存目录" in result:
                        protected_access_attempted = True
                    known_signatures.add(signature)
                    new_signatures.append(signature)
            duration_ms = (perf_counter() - started_at) * 1000
            observation, result = build_observation(
                observation_id=observation_id,
                tool_call_id=tool_call["id"],
                step=state["step_count"],
                tool_name=name,
                arguments_json=arguments,
                result_json=result,
                duration_ms=duration_ms,
                repeated=repeated,
            )
            observations.append(observation.model_dump(mode="json"))
            if (
                observation.ok
                and not observation.repeated
                and bool(current_hypotheses)
            ):
                new_successful_observation = True
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": result,
            })
        all_observations = existing_observations + [
            ToolObservation.model_validate(item) for item in observations
        ]
        sufficient = evidence_is_sufficient(current_hypotheses, all_observations)
        total_tool_calls = state.get("tool_call_count", 0) + len(calls)
        confirmed_at = state.get("confirmed_at_tool_call_count")
        if confirmed_at is None and any(
            item.status == "confirmed" for item in current_hypotheses
        ):
            confirmed_at = total_tool_calls
        early_stop_now = (
            sufficient
            and state["step_count"] < state["max_steps"]
            and state.get("model_call_count", 0)
            < max(1, state.get("max_model_calls", 10) - 2)
            and total_tool_calls < state.get("max_tool_calls", config.max_tool_calls)
        )
        pending_review_reason: str | None = None
        if state.get("human_review_enabled") and not state.get("human_review_triggered"):
            if protected_access_attempted:
                pending_review_reason = "protected_path"
            elif hypotheses_conflict(current_hypotheses):
                pending_review_reason = "conflicting_hypotheses"
            elif total_tool_calls >= state.get("hitl_tool_threshold", 10):
                pending_review_reason = "tool_budget_threshold"
            elif state.get("model_call_count", 0) >= state.get("hitl_model_threshold", 5):
                pending_review_reason = "model_budget_threshold"

        return {
            "messages": tool_messages,
            "tool_call_count": total_tool_calls,
            "tool_call_signatures": state.get("tool_call_signatures", []) + new_signatures,
            "repeated_tool_call_count": state.get("repeated_tool_call_count", 0) + repeated_count,
            # 第一次重复只返回反馈，允许模型改用已有结果或直接总结；同一次
            # 调查中第二次重复才强制关闭工具，避免一次偶发重试过早终止调查。
            "force_synthesis": (
                state.get("repeated_tool_call_count", 0) + repeated_count >= 2
                or len(calls) > remaining_budget
            ),
            "observations": observations,
            "hypotheses": [item.model_dump(mode="json") for item in current_hypotheses],
            "evidence_sufficient": sufficient,
            "early_stopped": state.get("early_stopped", False) or early_stop_now,
            "pending_review_reason": pending_review_reason,
            "confirmed_at_tool_call_count": confirmed_at,
            "hypothesis_update_required": (
                hypothesis_update_required or new_successful_observation
            ),
            "runtime_execution_decision": None,
            "runtime_call_count": runtime_call_count,
            "successful_runtime_call_count": successful_runtime_call_count,
            "runtime_timeout_count": runtime_timeout_count,
            "runtime_replay_count": runtime_replay_count,
        }

    def synthesize_report(state: AgentState) -> dict:
        """关闭工具能力，让模型必须根据已收集的观察结果输出报告。"""
        if state.get("early_stopped"):
            print("已确认假设获得充分独立证据，正在提前生成最终报告。")
        else:
            print("调查预算已用完或检测到重复调用，正在根据已有证据生成最终报告。")
        compacted_messages, compacted = request_messages(state, final_report=True)
        messages = compacted_messages + [{
            "role": "user",
            "content": (
                "停止调用工具。请只根据上面的用户输入和工具结果立即给出最终 JSON 报告。"
                "压缩记忆中 final_report_evidence_mode=true，observations 是最终证据候选；"
                "优先把其中具有 code/documentation/git/runtime 来源的成功 Observation 写入 Evidence。"
                "如果假设仍是 supported，只能输出 medium 或 low，不能输出 high；"
                "即使证据不足，也要说明缺少什么、降低 confidence，并给出下一步建议；"
                "不要返回空白兜底说明。"
            ),
        }]
        request = {"model": config.model, "messages": messages}
        output_format = response_format(config)
        if output_format is not None:
            request["response_format"] = output_format
        response = client.chat.completions.create(**request)
        return {
            "messages": [assistant_message_to_dict(response.choices[0].message)],
            "synthesis_attempted": True,
            "force_synthesis": False,
            "context_compaction_count": (
                state.get("context_compaction_count", 0) + int(compacted)
            ),
            **_model_usage_update(state, response),
        }

    def validate_report(state: AgentState) -> dict:
        content = state["messages"][-1].get("content")
        if not content:
            error = "模型没有返回最终报告"
        else:
            try:
                report = parse_incident_report(content)
                current_hypotheses = [
                    DiagnosticHypothesis.model_validate(item)
                    for item in state.get("hypotheses", [])
                ]
                hypothesis_errors = validate_hypothesis_readiness(
                    report,
                    current_hypotheses,
                )
                provenance_errors = validate_report_provenance(
                    report,
                    [
                        ToolObservation.model_validate(item)
                        for item in state.get("observations", [])
                    ],
                )
                validation_errors = hypothesis_errors + provenance_errors
                if validation_errors:
                    error = "诊断验证失败：" + "；".join(validation_errors)
                else:
                    return {
                        "report": report.model_dump(),
                        "validation_error": None,
                        "stop_reason": "completed",
                    }
            except ValidationError as exc:
                error = format_report_validation_error(exc)
        return {
            "messages": [{
                "role": "user",
                "content": (
                    f"{error}。如果缺少假设状态，请先调用 update_hypotheses；"
                    "否则请根据已有证据重新输出完整 JSON 报告。"
                ),
            }],
            "validation_error": error,
            "validation_errors": [error],
        }

    def repair_report(state: AgentState) -> dict:
        """强制总结格式不合法时，再进行一次无工具的结构化修复。"""
        print("最终报告格式不合法，正在进行一次无工具格式修复。")
        compacted_messages, compacted = request_messages(
            state,
            include_last_assistant=True,
            final_report=True,
        )
        messages = compacted_messages + [{
            "role": "user",
            "content": (
                "这是最后一次格式修复。不要调用工具，不要使用 Markdown 代码块，"
                "只输出一个合法 JSON 对象。必须完整包含 summary、root_cause、claims、"
                "evidence、suggested_fixes、confidence。保留并修正已有 observation_id；"
                "必须逐项解决压缩记忆中的 last_validation_error；若 high 缺少 confirmed "
                "假设就降为 medium/low，不要丢弃已经落地的成功证据；"
                "Git 提交使用 commit_hash，不能把目录、unknown 或 N/A 当作文件。"
            ),
        }]
        request = {"model": config.model, "messages": messages}
        output_format = response_format(config)
        if output_format is not None:
            request["response_format"] = output_format
        response = client.chat.completions.create(**request)
        return {
            "messages": [assistant_message_to_dict(response.choices[0].message)],
            "repair_attempted": True,
            "context_compaction_count": (
                state.get("context_compaction_count", 0) + int(compacted)
            ),
            **_model_usage_update(state, response),
        }

    def human_review(state: AgentState) -> dict:
        reason = state.get("pending_review_reason") or "manual_review"
        messages = {
            "protected_path": "Agent 尝试访问受保护路径，该访问仍会被安全边界拒绝。",
            "conflicting_hypotheses": "出现多个高置信度候选根因，需要人工决定是否继续取证。",
            "tool_budget_threshold": "工具调用已达到人工确认阈值。",
            "model_budget_threshold": "模型调用已达到人工确认阈值。",
        }
        request = HumanReviewRequest(
            reason=reason,
            message=messages.get(reason, "调查需要人工确认。"),
            model_call_count=state.get("model_call_count", 0),
            tool_call_count=state.get("tool_call_count", 0),
            hypotheses=[
                DiagnosticHypothesis.model_validate(item)
                for item in state.get("hypotheses", [])
            ],
            allowed_actions=["continue", "summarize", "cancel"],
        )
        decision = interrupt(request.model_dump(mode="json"))
        if isinstance(decision, dict):
            action = str(decision.get("action", "summarize")).lower()
        else:
            action = str(decision).lower()
        if action not in {"continue", "summarize", "cancel"}:
            action = "summarize"
        return {
            "messages": [{
                "role": "user",
                "content": f"人工决策：{action}。请遵守该决策。",
            }],
            "human_review_triggered": True,
            "human_review_count": state.get("human_review_count", 0) + 1,
            "pending_review_reason": None,
            "force_synthesis": action == "summarize",
            "cancelled": action == "cancel",
        }

    def build_fallback(state: AgentState) -> dict:
        hypotheses = [
            DiagnosticHypothesis.model_validate(item)
            for item in state.get("hypotheses", [])
        ]
        observations = {
            item.observation_id: item
            for item in (
                ToolObservation.model_validate(raw)
                for raw in state.get("observations", [])
            )
        }
        usable = [
            item
            for item in hypotheses
            if item.status in {"supported", "confirmed"}
            and item.supporting_observation_ids
        ]
        best = max(
            usable,
            key=lambda item: (
                item.status == "confirmed",
                item.confidence,
                len(item.supporting_observation_ids),
            ),
            default=None,
        )
        grounded_evidence: list[Evidence] = []
        if best is not None:
            for observation_id in dict.fromkeys(best.supporting_observation_ids):
                observation = observations.get(observation_id)
                if observation is None or not observation.ok or not observation.sources:
                    continue
                source = observation.sources[0]
                grounded_evidence.append(Evidence(
                    evidence_id=f"E{len(grounded_evidence) + 1}",
                    observation_id=observation_id,
                    source_type=source.source_type,
                    file=source.file,
                    line_start=source.line_start,
                    line_end=source.line_end,
                    commit_hash=source.commit_hash,
                    runtime_id=source.runtime_id,
                    description=f"{observation.tool_name} 已取得支持候选根因的真实来源。",
                ))
        if best is not None and grounded_evidence:
            evidence_ids = [item.evidence_id for item in grounded_evidence]
            report = IncidentReport(
                summary="模型报告格式修复失败，以下为系统根据已验证假设保留的降级报告。",
                root_cause=best.statement,
                claims=[DiagnosticClaim(
                    claim_id="C1",
                    statement=best.statement,
                    evidence_ids=evidence_ids,
                )],
                evidence=grounded_evidence,
                suggested_fixes=[
                    best.next_action.purpose
                    if best.next_action is not None
                    else "根据上述已落地证据修正对应配置或代码，并重新运行验证。"
                ],
                confidence=(
                    "high"
                    if evidence_is_sufficient([best], list(observations.values()))
                    else "medium"
                ),
            )
        else:
            report = IncidentReport(
                summary="已完成调查，但模型未能生成符合格式要求的最终报告。",
                root_cause="无法可靠解析最终结论；此前的工具观察结果仍保留在图状态中。",
                claims=[],
                evidence=[],
                suggested_fixes=["提供完整 traceback、实际启动命令和当前工作目录后重试。"],
                confidence="low",
            )
        return {"report": report.model_dump(), "stop_reason": "invalid_synthesis"}

    def build_cancelled(state: AgentState) -> dict:
        report = IncidentReport(
            summary="调查已按用户要求停止。",
            root_cause="用户在人工决策点终止调查；现有证据不足以形成最终根因。",
            claims=[],
            evidence=[],
            suggested_fixes=["如需继续，请使用相同问题重新启动调查并允许必要的只读取证。"],
            confidence="low",
        )
        return {"report": report.model_dump(), "stop_reason": "cancelled"}

    builder = StateGraph(AgentState)
    builder.add_node("call_model", call_model)
    builder.add_node("runtime_review", runtime_review)
    builder.add_node("execute_tools", execute_tools)
    builder.add_node("synthesize_report", synthesize_report)
    builder.add_node("repair_report", repair_report)
    builder.add_node("human_review", human_review)
    builder.add_node("validate_report", validate_report)
    builder.add_node("build_fallback", build_fallback)
    builder.add_node("build_cancelled", build_cancelled)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", route_after_model, {
        "execute_tools": "execute_tools",
        "runtime_review": "runtime_review",
        "validate_report": "validate_report",
        "build_fallback": "build_fallback",
    })
    builder.add_conditional_edges("runtime_review", route_after_runtime_review, {
        "execute_tools": "execute_tools",
        "build_cancelled": "build_cancelled",
    })
    builder.add_conditional_edges("execute_tools", route_after_tools, {
        "call_model": "call_model",
        "synthesize_report": "synthesize_report",
        "human_review": "human_review",
        "build_cancelled": "build_cancelled",
    })
    builder.add_conditional_edges("human_review", route_after_human_review, {
        "call_model": "call_model",
        "synthesize_report": "synthesize_report",
        "build_cancelled": "build_cancelled",
    })
    builder.add_edge("synthesize_report", "validate_report")
    builder.add_edge("repair_report", "validate_report")
    builder.add_conditional_edges("validate_report", route_after_validation, {
        "call_model": "call_model",
        "end": END,
        "build_fallback": "build_fallback",
        "synthesize_report": "synthesize_report",
        "repair_report": "repair_report",
    })
    builder.add_edge("build_fallback", END)
    builder.add_edge("build_cancelled", END)
    return builder.compile(checkpointer=checkpointer)
