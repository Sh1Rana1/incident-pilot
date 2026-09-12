"""V8.1.1 假设控制工具与确定性证据充分性判断。"""

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


HYPOTHESIS_TOOL_NAME = "update_hypotheses"


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
        if hypothesis.status in {"unverified", "supported"} and hypothesis.next_action is None:
            errors.append(
                f"{hypothesis.hypothesis_id} 的 {hypothesis.status} 状态缺少结构化 next_action"
            )
    if errors:
        return None, ToolResult.failure(
            "；".join(errors),
            tool=HYPOTHESIS_TOOL_NAME,
        ).model_dump_json()

    return update.hypotheses, ToolResult.success(
        {
            "hypothesis_count": len(update.hypotheses),
            "confirmed": [
                item.hypothesis_id
                for item in update.hypotheses
                if item.status == "confirmed"
            ],
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
