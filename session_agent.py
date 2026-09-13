"""V11 可跨进程恢复、可召回已批准历史线索的会话编排。"""

from time import perf_counter
from uuid import uuid4

from langgraph.types import Command

from agent import create_client
from graph import SYSTEM_PROMPT, build_agent_graph
from memory import format_memory_context, memory_candidate_fields
from models import (
    AgentRunResult,
    DiagnosticHypothesis,
    HumanReviewRequest,
    IncidentReport,
    RunMetrics,
    ToolObservation,
)
from session_store import SessionRecord, SessionStore
from tool_profiles import RUNTIME_TOOLS, resolve_tool_profile


def _runtime_config(thread_id: str) -> dict:
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 64,
    }


def _build_runtime(
    store: SessionStore,
    tool_profile: str,
    runtime_tools_enabled: bool,
):
    client, config = create_client()
    profile_name, profile_tools = resolve_tool_profile(tool_profile)
    # 持久化会话不能在恢复时自动获得新权限；当前环境
    # 开关又是 kill switch，中途关闭后可以立即撤销原会话能力。
    effective_runtime_enabled = (
        runtime_tools_enabled and config.runtime_tools_enabled
    )
    allowed_tools = (
        profile_tools
        if effective_runtime_enabled
        else profile_tools - RUNTIME_TOOLS
    )
    app = build_agent_graph(
        client,
        config,
        store.checkpointer,
        allowed_tools=allowed_tools,
        tool_profile=profile_name,
    )
    return app, config, profile_name


def _initial_state(
    question: str,
    thread_id: str,
    profile_name: str,
    config,
    runtime_tools_enabled: bool,
    ledger_path: str,
    memory_context: str = "",
    recalled_memory_count: int = 0,
) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + memory_context},
            {"role": "user", "content": question},
        ],
        "step_count": 0,
        "tool_call_count": 0,
        "max_steps": 8,
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
        "max_model_calls": config.max_model_calls,
        "max_tool_calls": config.max_tool_calls,
        "max_tools_per_step": config.max_tools_per_step,
        "evidence_sufficient": False,
        "early_stopped": False,
        "human_review_enabled": True,
        "human_review_triggered": False,
        "human_review_count": 0,
        "pending_review_reason": None,
        "hitl_model_threshold": config.hitl_model_threshold,
        "hitl_tool_threshold": config.hitl_tool_threshold,
        "cancelled": False,
        "context_compaction_count": 0,
        "confirmed_at_tool_call_count": None,
        "hypothesis_update_required": False,
        "runtime_tools_enabled": runtime_tools_enabled,
        "runtime_execution_preapproved": False,
        "runtime_execution_decision": None,
        "runtime_call_count": 0,
        "successful_runtime_call_count": 0,
        "runtime_timeout_count": 0,
        "runtime_approval_count": 0,
        "runtime_denial_count": 0,
        "runtime_replay_count": 0,
        "max_runtime_calls": config.max_runtime_calls,
        "runtime_ledger_path": ledger_path,
        "thread_id": thread_id,
        "recalled_memory_count": recalled_memory_count,
    }


def _interrupt_request(state: dict) -> HumanReviewRequest | None:
    interrupts = state.get("__interrupt__") or []
    if not interrupts:
        return None
    raw = interrupts[0]
    payload = getattr(raw, "value", raw)
    return HumanReviewRequest.model_validate(payload)


def _result_from_state(
    state: dict,
    profile_name: str,
    duration_ms: float,
) -> AgentRunResult:
    observations = [
        ToolObservation.model_validate(item) for item in state.get("observations", [])
    ]
    hypotheses = [
        DiagnosticHypothesis.model_validate(item)
        for item in state.get("hypotheses", [])
    ]
    report = IncidentReport.model_validate(state["report"])
    referenced_ids = {
        observation_id
        for hypothesis in hypotheses
        for observation_id in (
            hypothesis.supporting_observation_ids
            + hypothesis.contradicting_observation_ids
        )
    } | {item.observation_id for item in report.evidence}
    successful_ids = {item.observation_id for item in observations if item.ok}
    used_ids = referenced_ids & successful_ids
    utilization = (
        round(len(used_ids) / len(successful_ids), 4) if successful_ids else 1.0
    )
    tool_names = [
        call["function"]["name"]
        for message in state.get("messages", [])
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    ]
    confirmed_at = state.get("confirmed_at_tool_call_count")
    return AgentRunResult(
        report=report,
        metrics=RunMetrics(
            tool_profile=profile_name,
            model_call_count=state.get("model_call_count", 0),
            investigation_step_count=state.get("step_count", 0),
            tool_call_count=state.get("tool_call_count", 0),
            unique_tool_call_count=len(state.get("tool_call_signatures", [])),
            repeated_tool_call_count=state.get("repeated_tool_call_count", 0),
            observation_count=len(observations),
            successful_observation_count=sum(item.ok for item in observations),
            synthesis_used=state.get("synthesis_attempted", False),
            format_repair_used=state.get("repair_attempted", False),
            early_stopped=state.get("early_stopped", False),
            hypothesis_count=len(hypotheses),
            confirmed_hypothesis_count=sum(
                item.status == "confirmed" for item in hypotheses
            ),
            human_review_count=state.get("human_review_count", 0),
            protected_access_attempt_count=sum(
                bool(item.error and "属于评测或内部缓存目录" in item.error)
                for item in observations
            ),
            input_token_count=state.get("input_token_count", 0),
            output_token_count=state.get("output_token_count", 0),
            total_token_count=state.get("total_token_count", 0),
            context_compaction_count=state.get("context_compaction_count", 0),
            unreferenced_successful_observation_count=len(
                successful_ids - referenced_ids
            ),
            observation_utilization_rate=utilization,
            post_confirmation_tool_call_count=(
                max(0, state.get("tool_call_count", 0) - confirmed_at)
                if confirmed_at is not None
                else 0
            ),
            runtime_call_count=state.get("runtime_call_count", 0),
            successful_runtime_call_count=state.get(
                "successful_runtime_call_count", 0
            ),
            runtime_timeout_count=state.get("runtime_timeout_count", 0),
            runtime_approval_count=state.get("runtime_approval_count", 0),
            runtime_denial_count=state.get("runtime_denial_count", 0),
            runtime_replay_count=state.get("runtime_replay_count", 0),
            recalled_memory_count=state.get("recalled_memory_count", 0),
            tool_names=tool_names,
            stop_reason=state.get("stop_reason") or "unknown",
            duration_ms=round(duration_ms, 2),
        ),
        observations=observations,
        hypotheses=hypotheses,
        validation_errors=state.get("validation_errors", []),
    )


def _persist_outcome(
    store: SessionStore,
    thread_id: str,
    state: dict,
    profile_name: str,
) -> SessionRecord:
    request = _interrupt_request(state)
    if request is not None:
        return store.mark_waiting(thread_id, request)
    duration = store.get(thread_id).compute_duration_ms
    result = _result_from_state(state, profile_name, duration)
    record = store.mark_completed(thread_id, result)
    if record.status == "completed":
        fields = memory_candidate_fields(record.question, result)
        if fields is not None:
            store.create_memory_candidate(thread_id, fields)
    return record


def start_session(
    store: SessionStore,
    question: str,
    tool_profile: str = "full_runtime",
    thread_id: str | None = None,
) -> SessionRecord:
    resolved_thread_id = thread_id or str(uuid4())
    client, config = create_client()
    profile_name, profile_tools = resolve_tool_profile(tool_profile)
    runtime_enabled = bool(
        RUNTIME_TOOLS & profile_tools and config.runtime_tools_enabled
    )
    recalled = store.recall_memories(question)
    recalled_ids = [item.memory.memory_id for item in recalled]
    # 使用刚创建的 client，避免为了构图再次初始化客户端。
    allowed_tools = profile_tools if runtime_enabled else profile_tools - RUNTIME_TOOLS
    app = build_agent_graph(
        client,
        config,
        store.checkpointer,
        allowed_tools=allowed_tools,
        tool_profile=profile_name,
    )
    store.create(
        resolved_thread_id,
        question,
        profile_name,
        runtime_enabled,
        recalled_memory_ids=recalled_ids,
    )
    state = _initial_state(
        question,
        resolved_thread_id,
        profile_name,
        config,
        runtime_enabled,
        str(store.database_path),
        memory_context=format_memory_context(recalled),
        recalled_memory_count=len(recalled),
    )
    started = perf_counter()
    try:
        output = app.invoke(
            state,
            config=_runtime_config(resolved_thread_id),
            durability="sync",
        )
        store.add_compute_duration(
            resolved_thread_id,
            (perf_counter() - started) * 1000,
        )
        return _persist_outcome(store, resolved_thread_id, output, profile_name)
    except Exception as exc:
        store.add_compute_duration(
            resolved_thread_id,
            (perf_counter() - started) * 1000,
        )
        store.mark_failed(resolved_thread_id, str(exc))
        raise


def resume_session(
    store: SessionStore,
    thread_id: str,
    action: str,
) -> SessionRecord:
    record = store.get(thread_id)
    if record.pending_review is None or not record.status.startswith("waiting_for_"):
        raise ValueError(f"会话当前不在等待人工确认状态: {record.status}")
    if action not in record.pending_review.allowed_actions:
        allowed = ", ".join(record.pending_review.allowed_actions)
        raise ValueError(f"当前确认点不接受 {action}；可选: {allowed}")
    app, _config, profile_name = _build_runtime(
        store,
        record.tool_profile,
        record.runtime_tools_enabled,
    )
    started = perf_counter()
    try:
        output = app.invoke(
            Command(resume={"action": action}),
            config=_runtime_config(thread_id),
            durability="sync",
        )
        store.add_compute_duration(thread_id, (perf_counter() - started) * 1000)
        return _persist_outcome(store, thread_id, output, profile_name)
    except Exception as exc:
        store.add_compute_duration(thread_id, (perf_counter() - started) * 1000)
        store.mark_failed(thread_id, str(exc))
        raise
