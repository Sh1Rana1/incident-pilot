"""V8.1.1 模型上下文压缩：调查时精简，收尾时保全证据候选。"""

import json
from typing import Any

from models import DiagnosticHypothesis, ToolObservation


MAX_RECENT_UNREFERENCED_OBSERVATIONS = 4
MAX_OBSERVATION_EXCERPT_CHARS = 700
MAX_TARGETED_READ_EXCERPT_CHARS = 4_000


def _observation_excerpt(observation: ToolObservation) -> str:
    targeted_read = (
        observation.tool_name == "read_file"
        and (
            observation.arguments.get("start_line") is not None
            or observation.arguments.get("end_line") is not None
        )
    )
    limit = (
        MAX_TARGETED_READ_EXCERPT_CHARS
        if targeted_read
        else MAX_OBSERVATION_EXCERPT_CHARS
    )
    return observation.result_excerpt[:limit]


def _first_message(messages: list[dict], role: str) -> dict | None:
    return next((item for item in messages if item.get("role") == role), None)


def _selected_observations(
    observations: list[ToolObservation],
    hypotheses: list[DiagnosticHypothesis],
    final_report: bool = False,
) -> tuple[list[ToolObservation], int]:
    referenced_ids = {
        observation_id
        for hypothesis in hypotheses
        for observation_id in (
            hypothesis.supporting_observation_ids
            + hypothesis.contradicting_observation_ids
        )
    }
    referenced = [item for item in observations if item.observation_id in referenced_ids]
    if final_report:
        # 收尾时保留全部具有真实来源的成功结果。它们是最终 Evidence 的候选，
        # 即使模型忘记把它们写进假设，也不能因为普通轮次的窗口压缩而丢失。
        evidence_candidates = [item for item in observations if item.ok and item.sources]
        recent_failures = [item for item in observations if not item.ok][-2:]
        selected_ids = {
            item.observation_id
            for item in referenced + evidence_candidates + recent_failures
        }
        selected = [
            item for item in observations if item.observation_id in selected_ids
        ]
        return selected, len(observations) - len(selected)
    unreferenced = [
        item for item in observations if item.observation_id not in referenced_ids
    ]
    recent_unreferenced = unreferenced[-MAX_RECENT_UNREFERENCED_OBSERVATIONS:]
    selected_ids = {
        item.observation_id for item in referenced + recent_unreferenced
    }
    selected = [item for item in observations if item.observation_id in selected_ids]
    return selected, len(observations) - len(selected)


def compact_messages(
    messages: list[dict],
    observations: list[ToolObservation],
    hypotheses: list[DiagnosticHypothesis],
    validation_error: str | None = None,
    include_last_assistant: bool = False,
    final_report: bool = False,
) -> tuple[list[dict], bool]:
    """构造无悬空 tool_call 的最小请求上下文；完整状态仍留在 Checkpoint。"""
    if not observations and not hypotheses and not validation_error:
        return messages, False

    selected, omitted_count = _selected_observations(
        observations,
        hypotheses,
        final_report=final_report,
    )
    memory: dict[str, Any] = {
        "hypotheses": [item.model_dump(mode="json") for item in hypotheses],
        "observations": [
            {
                "observation_id": item.observation_id,
                "step": item.step,
                "tool_name": item.tool_name,
                "arguments": item.arguments,
                "ok": item.ok,
                "repeated": item.repeated,
                "sources": [source.model_dump(mode="json") for source in item.sources],
                "error": item.error,
                "result_excerpt": _observation_excerpt(item),
            }
            for item in selected
        ],
        "omitted_unreferenced_observation_count": omitted_count,
        "final_report_evidence_mode": final_report,
    }
    if validation_error:
        memory["last_validation_error"] = validation_error

    compacted: list[dict] = []
    system_message = _first_message(messages, "system")
    user_message = _first_message(messages, "user")
    if system_message:
        compacted.append(system_message)
    if user_message:
        compacted.append(user_message)
    compacted.append({
        "role": "system",
        "content": (
            "以下是系统生成的压缩调查记忆。它只用于继续推理；Observation ID、"
            "来源范围和失败状态必须原样遵守。未展示的未引用 Observation 仍保存在"
            "Checkpoint 中，但不应在最终报告中凭空引用。\n"
            + json.dumps(memory, ensure_ascii=False, separators=(",", ":"))
        ),
    })
    if include_last_assistant:
        last_assistant = next(
            (
                item
                for item in reversed(messages)
                if item.get("role") == "assistant"
                and item.get("content")
                and not item.get("tool_calls")
            ),
            None,
        )
        if last_assistant:
            compacted.append(last_assistant)
    return compacted, True
