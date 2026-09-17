"""V14 模型上下文压缩：保留定向窗口与搜索命中附近关键代码。"""

import json
from typing import Any

from models import DiagnosticHypothesis, ToolObservation


MAX_RECENT_UNREFERENCED_OBSERVATIONS = 4
MAX_OBSERVATION_EXCERPT_CHARS = 700
MAX_SEARCH_CODE_EXCERPT_CHARS = 6000
MAX_TARGETED_READ_EXCERPT_CHARS = 6000
MAX_CONTEXT_READ_LINES = 40
CONTEXT_READ_HEAD_LINES = 15
CONTEXT_READ_TAIL_LINES = 5
CONTEXT_ANCHOR_RADIUS = 3


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lower()


def _read_anchor_lines(
    observations: list[ToolObservation],
) -> dict[str, set[int]]:
    """收集搜索命中行，供大范围读取在压缩时保留邻近代码。"""
    anchors: dict[str, set[int]] = {}
    for observation in observations:
        if not observation.ok or observation.tool_name != "search_code":
            continue
        for source in observation.sources:
            if not source.file or source.line_start is None:
                continue
            anchors.setdefault(_normalized_path(source.file), set()).add(
                source.line_start
            )
    return anchors


def _compact_large_read_excerpt(
    observation: ToolObservation,
    anchor_lines: set[int],
) -> str:
    try:
        excerpt = json.loads(observation.result_excerpt)
    except (json.JSONDecodeError, TypeError):
        return observation.result_excerpt[:MAX_OBSERVATION_EXCERPT_CHARS]
    lines = excerpt.get("lines")
    if not isinstance(lines, list) or len(lines) <= 30:
        return observation.result_excerpt[:MAX_TARGETED_READ_EXCERPT_CHARS]

    available = {
        item.get("line"): item
        for item in lines
        if isinstance(item, dict) and isinstance(item.get("line"), int)
    }
    ordered_numbers = sorted(available)
    priority = list(ordered_numbers[:CONTEXT_READ_HEAD_LINES])
    for anchor in sorted(anchor_lines):
        priority.extend(
            number
            for number in range(
                anchor - CONTEXT_ANCHOR_RADIUS,
                anchor + CONTEXT_ANCHOR_RADIUS + 1,
            )
            if number in available
        )
    priority.extend(ordered_numbers[-CONTEXT_READ_TAIL_LINES:])
    selected_numbers = sorted(dict.fromkeys(priority[:MAX_CONTEXT_READ_LINES]))
    compact = {
        "path": excerpt.get("path", observation.arguments.get("path", "")),
        "requested_start_line": excerpt.get("requested_start_line"),
        "requested_end_line": excerpt.get("requested_end_line"),
        "lines": [available[number] for number in selected_numbers],
        "omitted_middle_line_count": max(0, len(lines) - len(selected_numbers)),
        "selection": "head_tail_and_search_hit_windows",
    }
    return json.dumps(compact, ensure_ascii=False)


def _observation_excerpt(
    observation: ToolObservation,
    read_anchors: dict[str, set[int]],
) -> str:
    """小窗口完整保留；大范围读取保留头尾与搜索命中附近代码。"""
    if observation.tool_name == "read_file":
        start = observation.arguments.get("start_line")
        end = observation.arguments.get("end_line")
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and end >= start
            and end - start + 1 <= 30
        ):
            return observation.result_excerpt[:MAX_TARGETED_READ_EXCERPT_CHARS]
        path = _normalized_path(str(observation.arguments.get("path", "")))
        return _compact_large_read_excerpt(
            observation,
            read_anchors.get(path, set()),
        )
    if observation.tool_name == "search_code":
        # 搜索命中是后续定向读取的索引；完整保留常规结果，避免路径排序
        # 靠后的 failure site / caller 只留下 source、却丢掉真实命中内容。
        return observation.result_excerpt[:MAX_SEARCH_CODE_EXCERPT_CHARS]
    return observation.result_excerpt[:MAX_OBSERVATION_EXCERPT_CHARS]


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
    read_anchors = _read_anchor_lines(observations)
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
                "result_excerpt": _observation_excerpt(item, read_anchors),
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
