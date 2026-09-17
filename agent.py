"""IncidentPilot V13 公开入口：诊断、补丁提案与可选隔离验证。"""

from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from openai import OpenAI

from config import AppConfig, load_config
from graph import SYSTEM_PROMPT, build_agent_graph
from models import (
    AgentRunResult,
    DiagnosticHypothesis,
    HumanReviewRequest,
    IncidentReport,
    PatchProposal,
    PatchVerificationResult,
    RunMetrics,
    ToolObservation,
)
from tool_profiles import resolve_tool_profile
from tool_profiles import RUNTIME_TOOLS


ROOT = Path(__file__).resolve().parent
CHECKPOINTER = InMemorySaver()
HumanReviewHandler = Callable[[HumanReviewRequest], str]


def create_client() -> tuple[OpenAI, AppConfig]:
    config = load_config(ROOT)
    return OpenAI(api_key=config.api_key, base_url=config.base_url), config


def run_agent_detailed(
    user_input: str,
    max_steps: int = 8,
    thread_id: str | None = None,
    tool_profile: str = "full",
    max_model_calls: int | None = None,
    max_tool_calls: int | None = None,
    human_review: bool = False,
    review_handler: HumanReviewHandler | None = None,
    allow_runtime_execution: bool = False,
    generate_patch_proposal: bool = False,
    verify_patch_proposal: bool = False,
) -> AgentRunResult:
    """运行状态图，并返回最终报告和可用于评测的运行指标。"""
    if human_review and review_handler is None:
        raise ValueError("启用 human_review 时必须提供 review_handler")
    if verify_patch_proposal and review_handler is None:
        raise ValueError("验证补丁时必须提供 review_handler 进行独立审批")
    client, config = create_client()
    profile_name, profile_tools = resolve_tool_profile(tool_profile)
    runtime_tools_enabled = bool(
        RUNTIME_TOOLS & profile_tools
        and (config.runtime_tools_enabled or allow_runtime_execution)
    )
    allowed_tools = (
        profile_tools
        if runtime_tools_enabled
        else profile_tools - RUNTIME_TOOLS
    )
    app = build_agent_graph(
        client,
        config,
        CHECKPOINTER,
        allowed_tools=allowed_tools,
        tool_profile=profile_name,
    )
    resolved_model_budget = max_model_calls or config.max_model_calls
    resolved_tool_budget = max_tool_calls or config.max_tool_calls
    resolved_thread_id = thread_id or str(uuid4())
    if resolved_model_budget < 3:
        raise ValueError("max_model_calls 必须大于等于 3，以保留总结和格式修复预算")
    if resolved_tool_budget < 1:
        raise ValueError("max_tool_calls 必须大于等于 1")
    initial_state = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
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
        "max_model_calls": resolved_model_budget,
        "max_tool_calls": resolved_tool_budget,
        "max_tools_per_step": config.max_tools_per_step,
        "evidence_sufficient": False,
        "early_stopped": False,
        "human_review_enabled": human_review,
        "human_review_triggered": False,
        "human_review_count": 0,
        "pending_review_reason": None,
        "hitl_model_threshold": config.hitl_model_threshold,
        "hitl_tool_threshold": config.hitl_tool_threshold,
        "cancelled": False,
        "context_compaction_count": 0,
        "confirmed_at_tool_call_count": None,
        "hypothesis_update_required": False,
        "final_classification_used": False,
        "runtime_tools_enabled": runtime_tools_enabled,
        "runtime_execution_preapproved": allow_runtime_execution,
        "runtime_execution_decision": None,
        "runtime_call_count": 0,
        "successful_runtime_call_count": 0,
        "runtime_timeout_count": 0,
        "runtime_approval_count": 0,
        "runtime_denial_count": 0,
        "runtime_replay_count": 0,
        "max_runtime_calls": config.max_runtime_calls,
        # 兼容入口使用内存 Checkpoint，不开启跨进程 Runtime 账本。
        "runtime_ledger_path": None,
        "thread_id": resolved_thread_id,
        "recalled_memory_count": 0,
        "patch_requested": generate_patch_proposal or verify_patch_proposal,
        "patch_attempted": False,
        "patch_proposal": None,
        "patch_validation_errors": [],
        "patch_verification_requested": verify_patch_proposal,
        "patch_verification_decision": None,
        "patch_verification_approval_count": 0,
        "patch_verification": None,
    }
    runtime_config = {
        "configurable": {"thread_id": resolved_thread_id},
        "recursion_limit": max_steps * 4 + 8,
    }
    started_at = perf_counter()
    final_state = app.invoke(initial_state, config=runtime_config)
    while final_state.get("__interrupt__"):
        raw_interrupt = final_state["__interrupt__"][0]
        payload = getattr(raw_interrupt, "value", raw_interrupt)
        request = HumanReviewRequest.model_validate(payload)
        decision = review_handler(request) if review_handler is not None else "summarize"
        final_state = app.invoke(
            Command(resume={"action": decision}),
            config=runtime_config,
        )
    duration_ms = (perf_counter() - started_at) * 1000
    observations = [
        ToolObservation.model_validate(item)
        for item in final_state.get("observations", [])
    ]
    hypotheses = [
        DiagnosticHypothesis.model_validate(item)
        for item in final_state.get("hypotheses", [])
    ]
    report = IncidentReport.model_validate(final_state["report"])
    patch_proposal = (
        PatchProposal.model_validate(final_state["patch_proposal"])
        if final_state.get("patch_proposal")
        else None
    )
    patch_verification = (
        PatchVerificationResult.model_validate(final_state["patch_verification"])
        if final_state.get("patch_verification")
        else None
    )
    referenced_observation_ids = {
        observation_id
        for hypothesis in hypotheses
        for observation_id in (
            hypothesis.supporting_observation_ids
            + hypothesis.contradicting_observation_ids
        )
    } | {item.observation_id for item in report.evidence}
    successful_observation_ids = {
        item.observation_id for item in observations if item.ok
    }
    used_successful_observations = (
        referenced_observation_ids & successful_observation_ids
    )
    unreferenced_successful_count = len(
        successful_observation_ids - referenced_observation_ids
    )
    utilization_rate = (
        round(
            len(used_successful_observations) / len(successful_observation_ids),
            4,
        )
        if successful_observation_ids
        else 1.0
    )

    tool_names = [
        call["function"]["name"]
        for message in final_state["messages"]
        if message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
    ]
    metrics = RunMetrics(
        tool_profile=profile_name,
        model_call_count=final_state.get(
            "model_call_count",
            sum(
                message.get("role") == "assistant"
                for message in final_state["messages"]
            ),
        ),
        investigation_step_count=final_state["step_count"],
        tool_call_count=final_state["tool_call_count"],
        unique_tool_call_count=len(final_state.get("tool_call_signatures", [])),
        repeated_tool_call_count=final_state.get("repeated_tool_call_count", 0),
        observation_count=len(observations),
        successful_observation_count=sum(item.ok for item in observations),
        synthesis_used=final_state.get("synthesis_attempted", False),
        format_repair_used=final_state.get("repair_attempted", False),
        early_stopped=final_state.get("early_stopped", False),
        hypothesis_count=len(hypotheses),
        confirmed_hypothesis_count=sum(
            item.status == "confirmed" for item in hypotheses
        ),
        human_review_count=final_state.get("human_review_count", 0),
        protected_access_attempt_count=sum(
            bool(item.error and "属于评测或内部缓存目录" in item.error)
            for item in observations
        ),
        input_token_count=final_state.get("input_token_count", 0),
        output_token_count=final_state.get("output_token_count", 0),
        total_token_count=final_state.get("total_token_count", 0),
        context_compaction_count=final_state.get("context_compaction_count", 0),
        unreferenced_successful_observation_count=unreferenced_successful_count,
        observation_utilization_rate=utilization_rate,
        post_confirmation_tool_call_count=max(
            0,
            final_state.get("tool_call_count", 0)
            - final_state.get("confirmed_at_tool_call_count", final_state.get("tool_call_count", 0)),
        ) if final_state.get("confirmed_at_tool_call_count") is not None else 0,
        runtime_call_count=final_state.get("runtime_call_count", 0),
        successful_runtime_call_count=final_state.get(
            "successful_runtime_call_count", 0
        ),
        runtime_timeout_count=final_state.get("runtime_timeout_count", 0),
        runtime_approval_count=final_state.get("runtime_approval_count", 0),
        runtime_denial_count=final_state.get("runtime_denial_count", 0),
        runtime_replay_count=final_state.get("runtime_replay_count", 0),
        recalled_memory_count=final_state.get("recalled_memory_count", 0),
        patch_requested=generate_patch_proposal or verify_patch_proposal,
        patch_proposal_generated=patch_proposal is not None,
        patch_proposal_valid=bool(
            patch_proposal and patch_proposal.status == "validated"
        ),
        patch_verification_requested=verify_patch_proposal,
        patch_verification_approval_count=final_state.get(
            "patch_verification_approval_count", 0
        ),
        patch_verification_check_count=(
            len(patch_verification.check_runs) if patch_verification else 0
        ),
        patch_verified=bool(
            patch_verification and patch_verification.status == "verified"
        ),
        tool_names=tool_names,
        stop_reason=final_state.get("stop_reason") or "unknown",
        duration_ms=round(duration_ms, 2),
    )
    return AgentRunResult(
        report=report,
        metrics=metrics,
        observations=observations,
        hypotheses=hypotheses,
        validation_errors=final_state.get("validation_errors", []),
        patch_proposal=patch_proposal,
        patch_validation_errors=final_state.get("patch_validation_errors", []),
        patch_verification=patch_verification,
    )


def run_agent(
    user_input: str,
    max_steps: int = 8,
    thread_id: str | None = None,
    tool_profile: str = "full",
    max_model_calls: int | None = None,
    max_tool_calls: int | None = None,
    human_review: bool = False,
    review_handler: HumanReviewHandler | None = None,
    allow_runtime_execution: bool = False,
    generate_patch_proposal: bool = False,
    verify_patch_proposal: bool = False,
) -> IncidentReport:
    """兼容原有调用方：只返回报告。"""
    return run_agent_detailed(
        user_input,
        max_steps,
        thread_id,
        tool_profile,
        max_model_calls,
        max_tool_calls,
        human_review,
        review_handler,
        allow_runtime_execution,
        generate_patch_proposal,
        verify_patch_proposal,
    ).report
