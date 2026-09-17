"""V14 假设控制、下一动作信息增益与确定性证据充分性判断。"""

import json
from typing import Any

from pydantic import ValidationError

from models import (
    DiagnosticHypothesis,
    HypothesisUpdate,
    IncidentReport,
    ToolObservation,
    ToolResult,
)
from registry import registry


HYPOTHESIS_TOOL_NAME = "update_hypotheses"


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lower()


def _redundant_next_action(
    hypothesis: DiagnosticHypothesis,
    observations: list[ToolObservation],
) -> str | None:
    """返回已被成功 Observation 覆盖的 next_action 说明。"""
    action = hypothesis.next_action
    if action is None:
        return None
    expected_arguments, error = registry.normalize_arguments(
        action.tool_name,
        action.arguments,
    )
    if error or expected_arguments is None:
        return None

    successful = [
        item for item in observations if item.ok and not item.repeated
    ]
    for observation in successful:
        if observation.tool_name != action.tool_name:
            continue
        actual_arguments, actual_error = registry.normalize_arguments(
            observation.tool_name,
            observation.arguments,
        )
        if not actual_error and actual_arguments == expected_arguments:
            return f"已由 {observation.observation_id} 成功执行"

    if action.tool_name != "read_file":
        return None
    path = _normalized_path(str(expected_arguments.get("path", "")))
    requested_start = expected_arguments.get("start_line") or 1
    requested_end = expected_arguments.get("end_line")
    if not path or requested_end is None:
        return None

    intervals: list[tuple[int, int, str]] = []
    for observation in successful:
        if observation.tool_name != "read_file":
            continue
        for source in observation.sources:
            if (
                _normalized_path(source.file) == path
                and source.line_start is not None
                and source.line_end is not None
            ):
                intervals.append((
                    source.line_start,
                    source.line_end,
                    observation.observation_id,
                ))
    covered_until = requested_start - 1
    covering_ids: list[str] = []
    for start, end, observation_id in sorted(intervals, key=lambda item: item[0]):
        if end < requested_start:
            continue
        if start > covered_until + 1:
            break
        if end > covered_until:
            covered_until = end
            covering_ids.append(observation_id)
        if covered_until >= requested_end:
            return "读取范围已由成功 Observation 覆盖: " + ",".join(
                dict.fromkeys(covering_ids)
            )
    return None


def hypothesis_tool_schema(strict: bool = False) -> dict[str, Any]:
    """返回只更新图状态、不访问工作区的内部工具 Schema。"""
    schema = HypothesisUpdate.model_json_schema()
    function: dict[str, Any] = {
        "name": HYPOTHESIS_TOOL_NAME,
        "description": (
            "更新当前完整诊断假设集合。先提出可证伪假设；获得 Observation 后，"
            "用 supporting_observation_ids 或 contradicting_observation_ids 更新状态。"
        ),
        "parameters": schema,
    }
    if strict:
        function["strict"] = True
    return {"type": "function", "function": function}


def parse_hypothesis_update(
    arguments_json: str,
    observations: list[ToolObservation],
    allowed_tools: frozenset[str] | set[str] | None = None,
    *,
    require_next_action: bool = True,
) -> tuple[list[DiagnosticHypothesis] | None, str]:
    """校验假设 ID、Observation 引用和状态，返回标准工具结果 JSON。"""
    try:
        update = HypothesisUpdate.model_validate_json(arguments_json)
    except ValidationError as exc:
        return None, ToolResult.failure(
            f"假设格式错误: {exc.error_count()} 处",
            tool=HYPOTHESIS_TOOL_NAME,
        ).model_dump_json()

    ids = [item.hypothesis_id for item in update.hypotheses]
    if len(ids) != len(set(ids)):
        return None, ToolResult.failure(
            "hypothesis_id 不能重复",
            tool=HYPOTHESIS_TOOL_NAME,
        ).model_dump_json()

    observation_map = {item.observation_id: item for item in observations}
    errors: list[str] = []
    action_warnings: list[str] = []
    sanitized_hypotheses: list[DiagnosticHypothesis] = []
    for hypothesis in update.hypotheses:
        referenced = (
            hypothesis.supporting_observation_ids
            + hypothesis.contradicting_observation_ids
        )
        missing = [item for item in referenced if item not in observation_map]
        failed = [
            item
            for item in referenced
            if item in observation_map and not observation_map[item].ok
        ]
        if missing:
            errors.append(
                f"{hypothesis.hypothesis_id} 引用了不存在的 Observation: {','.join(missing)}"
            )
        if failed:
            errors.append(
                f"{hypothesis.hypothesis_id} 引用了失败的 Observation: {','.join(failed)}"
            )
        if hypothesis.status in {"supported", "confirmed"} and not hypothesis.supporting_observation_ids:
            errors.append(f"{hypothesis.hypothesis_id} 的 {hypothesis.status} 状态缺少支持证据")
        if hypothesis.status == "rejected" and not hypothesis.contradicting_observation_ids:
            errors.append(f"{hypothesis.hypothesis_id} 的 rejected 状态缺少反证")
        sanitized = hypothesis
        if not require_next_action:
            # 终局归类之后图会立即总结，不会再开放外部工具。此时保留或
            # 强制要求 next_action 都没有意义，也不应让陈旧动作阻断证据归类。
            sanitized = hypothesis.model_copy(update={"next_action": None})
        elif hypothesis.next_action is not None:
            action_error = registry.validate_arguments(
                hypothesis.next_action.tool_name,
                hypothesis.next_action.arguments,
                allowed_tools=allowed_tools,
            )
            if action_error:
                action_warnings.append(
                    f"{hypothesis.hypothesis_id} 的 next_action 无效: {action_error}"
                )
                sanitized = hypothesis.model_copy(update={"next_action": None})
            else:
                redundant = _redundant_next_action(hypothesis, observations)
                if redundant:
                    action_warnings.append(
                        f"{hypothesis.hypothesis_id} 的 next_action 没有新增信息: "
                        f"{redundant}；请规划尚未执行且能区分假设的动作"
                    )
                    sanitized = hypothesis.model_copy(update={"next_action": None})
        sanitized_hypotheses.append(sanitized)

    if require_next_action:
        open_hypotheses = [
            item for item in sanitized_hypotheses
            if item.status in {"unverified", "supported"}
        ]
        if open_hypotheses and not any(
            item.next_action is not None for item in open_hypotheses
        ):
            errors.append(
                "完整假设集合至少需要一个 unverified/supported 假设提供结构化 next_action"
            )
    if errors:
        return None, ToolResult.failure(
            "；".join(action_warnings + errors),
            tool=HYPOTHESIS_TOOL_NAME,
        ).model_dump_json()

    return sanitized_hypotheses, ToolResult.success(
        {
            "hypothesis_count": len(sanitized_hypotheses),
            "confirmed": [
                item.hypothesis_id
                for item in sanitized_hypotheses
                if item.status == "confirmed"
            ],
            "ignored_next_actions": action_warnings,
        },
        tool=HYPOTHESIS_TOOL_NAME,
    ).model_dump_json()


def evidence_is_sufficient(
    hypotheses: list[DiagnosticHypothesis],
    observations: list[ToolObservation],
) -> bool:
    """至少两项独立成功来源支持高置信度 confirmed 假设时允许提前总结。"""
    observation_map = {item.observation_id: item for item in observations}
    for hypothesis in hypotheses:
        if hypothesis.status != "confirmed" or hypothesis.confidence < 0.8:
            continue
        supporting = [
            observation_map[item]
            for item in dict.fromkeys(hypothesis.supporting_observation_ids)
            if item in observation_map and observation_map[item].ok
        ]
        if len(supporting) < 2 or hypothesis.contradicting_observation_ids:
            continue
        source_types = {
            source.source_type
            for observation in supporting
            for source in observation.sources
            if source.source_type != "unknown"
        }
        files = {
            source.file
            for observation in supporting
            for source in observation.sources
            if source.file
        }
        if len(source_types) >= 2 or len(files) >= 2:
            return True
    return False


def hypotheses_conflict(hypotheses: list[DiagnosticHypothesis]) -> bool:
    """多个不同高置信度根因同时被确认时请求人工判断。"""
    confirmed = [
        item
        for item in hypotheses
        if item.status == "confirmed" and item.confidence >= 0.8
    ]
    return len(confirmed) > 1


def validate_hypothesis_readiness(
    report: IncidentReport,
    hypotheses: list[DiagnosticHypothesis],
) -> list[str]:
    """中高置信度报告必须先经过显式假设验证阶段。"""
    if report.confidence == "high" and not any(
        item.status == "confirmed" for item in hypotheses
    ):
        return ["high 置信度报告缺少 confirmed 诊断假设"]
    if report.confidence == "medium" and not any(
        item.status in {"supported", "confirmed"} for item in hypotheses
    ):
        return ["medium 置信度报告缺少 supported 或 confirmed 诊断假设"]
    return []
