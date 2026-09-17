"""V14 工具 Observation 与代码、文档、Git、Harness Runtime 来源验证。"""

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

from models import Evidence, IncidentReport, ObservedSource, ToolObservation


MAX_RESULT_EXCERPT_CHARS = 1000
MAX_SEARCH_CODE_EXCERPT_CHARS = 6000
MAX_READ_FILE_EXCERPT_CHARS = 50000
MAX_READ_FILE_EXCERPT_LINES = 30


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lower()


def _source_type(path: str) -> str:
    normalized = _normalized_path(path)
    suffix = PurePosixPath(normalized).suffix.lower()
    if suffix == ".md":
        return "documentation"
    if "/logs/" in f"/{normalized}" or suffix == ".log":
        return "runtime"
    if suffix == ".py":
        return "code"
    return "unknown"


def _file_source(path: str, line_start=None, line_end=None, **extra) -> ObservedSource:
    return ObservedSource(
        source_type=_source_type(path),
        file=path,
        line_start=line_start,
        line_end=line_end,
        **extra,
    )


def _extract_git_diff_sources(output: str) -> list[ObservedSource]:
    sources: list[ObservedSource] = []
    current_file = ""
    for line in output.splitlines():
        match = re.match(r"diff --git a/(.+?) b/(.+)$", line)
        if match:
            current_file = match.group(2)
            continue
        hunk = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if hunk and current_file:
            start = int(hunk.group(1))
            count = int(hunk.group(2) or "1")
            end = start + max(count - 1, 0)
            sources.append(ObservedSource(
                source_type="git",
                file=current_file,
                line_start=start,
                line_end=end,
            ))
    return sources


def extract_observed_sources(tool_name: str, result_payload: dict[str, Any]) -> list[ObservedSource]:
    if not result_payload.get("ok"):
        return []
    data = result_payload.get("data") or {}
    if tool_name == "read_file":
        lines = data.get("lines") or []
        numbers = [item.get("line") for item in lines if isinstance(item.get("line"), int)]
        return [_file_source(
            data.get("path", ""),
            min(numbers) if numbers else None,
            max(numbers) if numbers else None,
        )] if data.get("path") else []
    if tool_name == "search_code":
        return [
            _file_source(item.get("path", ""), item.get("line"), item.get("line"))
            for item in data.get("matches", [])
            if item.get("path")
        ]
    if tool_name == "retrieve_docs":
        return [
            ObservedSource(
                source_type="documentation",
                file=item.get("source", ""),
                line_start=item.get("line_start"),
                line_end=item.get("line_end"),
                chunk_id=item.get("chunk_id"),
            )
            for item in data.get("chunks", [])
            if item.get("source")
        ]
    if tool_name in {"run_demo_case", "run_check"} and data.get("run_id"):
        return [ObservedSource(
            source_type="runtime",
            runtime_id=data["run_id"],
        )]
    output = data.get("output", "")
    if tool_name == "git_log":
        return [
            ObservedSource(source_type="git", commit_hash=line.split("\t", 1)[0])
            for line in output.splitlines()
            if re.fullmatch(r"[0-9a-fA-F]{7,40}", line.split("\t", 1)[0])
        ]
    if tool_name == "git_diff":
        return _extract_git_diff_sources(output)
    if tool_name == "git_status":
        sources = []
        for line in output.splitlines():
            if line.startswith("##") or len(line) < 4:
                continue
            path = line[3:].split(" -> ")[-1].strip()
            if path:
                sources.append(ObservedSource(source_type="git", file=path))
        return sources
    return []


def _result_excerpt(
    tool_name: str,
    payload: dict[str, Any],
    arguments: dict[str, Any],
) -> str:
    """为模型记忆生成保留关键行、但不替代原始工具结果的紧凑摘录。"""
    if tool_name == "search_code" and payload.get("ok"):
        # 搜索结果通常由多条短命中组成。只保留通用的 1,000 字符会让
        # 排在后面的 failure site / caller 命中从下一轮上下文中消失，
        # 诱导模型再次搜索。这里保留完整的常规搜索结果，同时仍设硬上限。
        return json.dumps(payload, ensure_ascii=False)[:MAX_SEARCH_CODE_EXCERPT_CHARS]
    if tool_name != "read_file" or not payload.get("ok"):
        return json.dumps(payload, ensure_ascii=False)[:MAX_RESULT_EXCERPT_CHARS]

    data = payload.get("data") or {}
    lines = data.get("lines") or []
    targeted = arguments.get("start_line") is not None or arguments.get("end_line") is not None
    selected = lines
    omitted = 0
    if not targeted and len(lines) > MAX_READ_FILE_EXCERPT_LINES:
        half = MAX_READ_FILE_EXCERPT_LINES // 2
        selected = lines[:half] + lines[-half:]
        omitted = len(lines) - len(selected)
    compact = {
        "path": data.get("path", ""),
        "requested_start_line": arguments.get("start_line"),
        "requested_end_line": arguments.get("end_line"),
        "lines": selected,
    }
    if omitted:
        compact["omitted_middle_line_count"] = omitted
    serialized = json.dumps(compact, ensure_ascii=False)
    if len(serialized) > MAX_READ_FILE_EXCERPT_CHARS and len(selected) > 2:
        half = MAX_READ_FILE_EXCERPT_LINES // 2
        compact["lines"] = selected[:half] + selected[-half:]
        compact["omitted_middle_line_count"] = max(0, len(lines) - 2 * half)
        serialized = json.dumps(compact, ensure_ascii=False)
    if len(serialized) > MAX_READ_FILE_EXCERPT_CHARS:
        compact["lines"] = [
            {
                **item,
                "content": str(item.get("content", ""))[:1000],
            }
            for item in compact.get("lines", [])
            if isinstance(item, dict)
        ]
        compact["line_content_truncated"] = True
        serialized = json.dumps(compact, ensure_ascii=False)
    return serialized


def build_observation(
    observation_id: str,
    tool_call_id: str,
    step: int,
    tool_name: str,
    arguments_json: str,
    result_json: str,
    duration_ms: float,
    repeated: bool = False,
) -> tuple[ToolObservation, str]:
    try:
        arguments = json.loads(arguments_json)
    except (json.JSONDecodeError, TypeError):
        arguments = {"raw": str(arguments_json)}
    try:
        payload = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        payload = {"ok": False, "error": "工具返回了无法解析的结果", "data": None, "meta": {}}
    payload.setdefault("meta", {})["observation_id"] = observation_id
    result_with_id = json.dumps(payload, ensure_ascii=False)
    observation = ToolObservation(
        observation_id=observation_id,
        tool_call_id=tool_call_id,
        step=step,
        tool_name=tool_name,
        arguments=arguments,
        ok=bool(payload.get("ok")) and not repeated,
        repeated=repeated,
        sources=extract_observed_sources(tool_name, payload),
        error=payload.get("error"),
        result_sha256=hashlib.sha256(result_with_id.encode("utf-8")).hexdigest(),
        result_excerpt=_result_excerpt(tool_name, payload, arguments),
        duration_ms=round(duration_ms, 2),
    )
    return observation, result_with_id


def evidence_is_grounded(evidence: Evidence, observation: ToolObservation | None) -> bool:
    if observation is None or not observation.ok or observation.repeated:
        return False
    normalized_file = _normalized_path(evidence.file)
    for source in observation.sources:
        if source.source_type != evidence.source_type:
            continue
        if evidence.source_type == "git" and evidence.commit_hash:
            if source.commit_hash and source.commit_hash.lower().startswith(
                evidence.commit_hash.lower()
            ):
                return True
            continue
        if evidence.source_type == "runtime" and evidence.runtime_id:
            if source.runtime_id == evidence.runtime_id:
                return True
            continue
        if not evidence.file or _normalized_path(source.file) != normalized_file:
            continue
        if evidence.line_start is None and evidence.line_end is None:
            return True
        if source.line_start is None or source.line_end is None:
            continue
        requested_start = evidence.line_start or evidence.line_end
        requested_end = evidence.line_end or evidence.line_start
        if (
            requested_start is not None
            and requested_end is not None
            and requested_start <= requested_end
            and source.line_start <= requested_start
            and requested_end <= source.line_end
        ):
            return True
    return False


def validate_report_provenance(
    report: IncidentReport,
    observations: list[ToolObservation],
) -> list[str]:
    errors: list[str] = []
    observation_map = {item.observation_id: item for item in observations}
    evidence_ids = [item.evidence_id for item in report.evidence]
    if len(set(evidence_ids)) != len(evidence_ids):
        errors.append("evidence_id 必须唯一")
    claim_ids = [item.claim_id for item in report.claims]
    if len(set(claim_ids)) != len(claim_ids):
        errors.append("claim_id 必须唯一")
    evidence_id_set = set(evidence_ids)
    referenced_evidence: set[str] = set()
    for claim in report.claims:
        if not claim.evidence_ids:
            errors.append(f"Claim {claim.claim_id} 没有绑定证据")
        missing = [item for item in claim.evidence_ids if item not in evidence_id_set]
        if missing:
            errors.append(f"Claim {claim.claim_id} 引用了不存在的证据: {', '.join(missing)}")
        referenced_evidence.update(claim.evidence_ids)
    if report.confidence != "low" and not report.claims:
        errors.append("medium/high 报告必须包含至少一个有证据的 Claim")
    unreferenced = evidence_id_set - referenced_evidence
    if unreferenced:
        errors.append(f"存在未被 Claim 使用的证据: {', '.join(sorted(unreferenced))}")
    for evidence in report.evidence:
        observation = observation_map.get(evidence.observation_id)
        if observation is None:
            errors.append(
                f"Evidence {evidence.evidence_id} 引用了不存在的 Observation "
                f"{evidence.observation_id}"
            )
        elif not evidence_is_grounded(evidence, observation):
            errors.append(
                f"Evidence {evidence.evidence_id} 的文件、行号、提交或来源类型"
                f"不在 {evidence.observation_id} 的真实工具结果中"
            )
    return errors
