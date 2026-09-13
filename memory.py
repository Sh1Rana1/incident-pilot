"""V10.2 长期事故记忆：确定性提取、词法召回和安全上下文。"""

import re
from typing import Any

from models import AgentRunResult, IncidentMemory, IncidentMemoryMatch


MAX_RECALLED_MEMORIES = 3
_EXCEPTION_PATTERN = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)\b"
)
_SYMBOL_PATTERN = re.compile(
    r"[`'\"]([A-Za-z_][A-Za-z0-9_.-]{2,80})[`'\"]"
)
_ASCII_TOKEN_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_.-]{1,80}")
_CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")


def _unique(values: list[str], limit: int = 20) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:limit]


def memory_candidate_fields(
    question: str,
    result: AgentRunResult,
) -> dict[str, Any] | None:
    """只将正常完成、中高置信度且有落地证据的调查变成候选记忆。"""
    report = result.report
    if (
        result.metrics.stop_reason != "completed"
        or report.confidence not in {"medium", "high"}
        or not report.claims
        or not report.evidence
    ):
        return None
    evidence_ids = {item.evidence_id for item in report.evidence}
    if any(
        not claim.evidence_ids
        or not set(claim.evidence_ids).issubset(evidence_ids)
        for claim in report.claims
    ):
        return None

    text = "\n".join([question, report.summary, report.root_cause])
    exception_types = _unique(
        [item.rsplit(".", 1)[-1] for item in _EXCEPTION_PATTERN.findall(text)]
    )
    symbols = _unique(_SYMBOL_PATTERN.findall(text))
    files = _unique([item.file for item in report.evidence if item.file])
    return {
        "exception_types": exception_types,
        "symbols": symbols,
        "files": files,
        "summary": report.summary[:1000],
        "root_cause": report.root_cause[:2000],
        "resolution": [item[:1000] for item in report.suggested_fixes[:8]],
        "source_confidence": report.confidence,
    }


def _tokens(text: str) -> set[str]:
    normalized = text.lower()
    tokens = {item.lower() for item in _ASCII_TOKEN_PATTERN.findall(normalized)}
    for block in _CHINESE_PATTERN.findall(normalized):
        tokens.update(block[index:index + 2] for index in range(len(block) - 1))
    return tokens


def memory_search_text(memory: IncidentMemory) -> str:
    return "\n".join([
        *memory.exception_types,
        *memory.symbols,
        *memory.files,
        memory.summary,
        memory.root_cause,
        *memory.resolution,
    ])


def memory_similarity(query: str, memory: IncidentMemory) -> float:
    """可解释的本地评分：词汇覆盖率 + 异常/符号精确命中加权。"""
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    memory_tokens = _tokens(memory_search_text(memory))
    overlap = len(query_tokens & memory_tokens) / len(query_tokens)
    query_lower = query.lower()
    exact = sum(
        1
        for value in memory.exception_types + memory.symbols
        if value.lower() in query_lower
    )
    return round(overlap + min(exact, 3) * 0.35, 4)


def rank_memories(
    query: str,
    memories: list[IncidentMemory],
    limit: int = MAX_RECALLED_MEMORIES,
) -> list[IncidentMemoryMatch]:
    matches = [
        IncidentMemoryMatch(memory=memory, score=memory_similarity(query, memory))
        for memory in memories
        if memory.status == "approved"
    ]
    matches = [item for item in matches if item.score > 0]
    return sorted(
        matches,
        key=lambda item: (-item.score, item.memory.memory_id),
    )[:limit]


def format_memory_context(matches: list[IncidentMemoryMatch]) -> str:
    if not matches:
        return ""
    items = []
    for match in matches:
        memory = match.memory
        items.append(
            f"- {memory.memory_id} (similarity={match.score:.3f}): "
            f"历史根因={memory.root_cause}; "
            f"历史处理={'; '.join(memory.resolution) or '未记录'}; "
            f"涉及文件={', '.join(memory.files) or '未记录'}"
        )
    return (
        "\n\n以下是系统召回的已批准历史事故，只能用于提出候选假设：\n"
        + "\n".join(items)
        + "\n安全规则：历史 Memory 不是当前 Observation，不能作为 Evidence，"
        "不能在 Claim 中引用，也不能用它提高置信度。必须用当前"
        "项目的代码、文档、Git 或 Runtime Observation 重新验证。"
    )
