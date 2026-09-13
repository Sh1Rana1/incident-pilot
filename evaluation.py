"""IncidentPilot 的确定性评测模型、评分规则与批量运行逻辑。"""

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from statistics import mean
from typing import Optional

from pydantic import Field

from models import (
    AgentRunResult,
    DiagnosticHypothesis,
    Evidence,
    IncidentReport,
    RunMetrics,
    StrictModel,
    ToolObservation,
)
from provenance import evidence_is_grounded, validate_report_provenance


class EvaluationCase(StrictModel):
    case_id: str
    question: str
    expected_exception: str
    root_cause_keywords: list[str]
    evidence_files: list[str]
    relevant_docs: list[str]
    requires_runtime_evidence: bool = False


class CaseScores(StrictModel):
    expected_exception_mentioned: bool
    root_cause_keyword_hits: int
    root_cause_keyword_total: int
    root_cause_keyword_rate: float
    evidence_file_hits: int
    evidence_file_total: int
    evidence_file_rate: float
    relevant_doc_hits: int
    relevant_doc_total: int
    relevant_doc_rate: float
    valid_citations: int
    invalid_citations: int
    citation_validity_rate: float
    grounded_evidence_count: int
    evidence_total: int
    evidence_grounded_rate: float
    supported_claim_count: int
    claim_total: int
    claim_coverage_rate: float
    provenance_violation_count: int
    runtime_evidence_count: int
    runtime_evidence_required: bool
    failure_reasons: list[str]
    passed: bool


class CaseEvaluation(StrictModel):
    case_id: str
    question: str
    profile: str = "full"
    run_index: int = 1
    report: IncidentReport
    metrics: RunMetrics
    observations: list[ToolObservation]
    hypotheses: list[DiagnosticHypothesis]
    validation_errors: list[str] = Field(default_factory=list)
    scores: CaseScores


class EvaluationSummary(StrictModel):
    case_count: int
    passed_count: int
    pass_rate: float
    average_root_cause_keyword_rate: float
    average_evidence_file_rate: float
    average_relevant_doc_rate: float
    average_citation_validity_rate: float
    average_model_call_count: float
    average_tool_call_count: float
    total_duration_ms: float


class EvaluationRun(StrictModel):
    cases: list[CaseEvaluation]
    summary: EvaluationSummary


AgentRunner = Callable[[str, int], AgentRunResult]


def _rate(hits: int, total: int) -> float:
    return round(hits / total, 4) if total else 1.0


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lower()


def _report_text(report: IncidentReport) -> str:
    return "\n".join([
        report.summary,
        report.root_cause,
        *report.suggested_fixes,
        *(item.description for item in report.evidence),
    ]).lower()


def _root_cause_text(report: IncidentReport) -> str:
    # V7 把可验证的诊断结论拆进 Claim—Evidence Ledger。Claim 属于根因
    # 陈述的一部分，不能只因为模型把精确数值写在 Claim 而非 root_cause
    # 字段中，就把语义完整的报告判成失败。修复建议和证据描述仍不参与，
    # 避免模型在非结论区域堆砌关键词。
    return "\n".join([
        report.summary,
        report.root_cause,
        *(claim.statement for claim in report.claims),
    ]).lower()


def _citation_is_valid(project_root: Path, evidence: Evidence) -> bool:
    """验证证据文件存在，且可选行号落在真实文件范围内。"""
    if evidence.source_type == "git":
        return bool(evidence.commit_hash or evidence.file)
    if evidence.source_type == "runtime":
        return bool(evidence.runtime_id)
    if not evidence.file:
        return False
    root = project_root.resolve()
    candidate = (root / evidence.file).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    if not candidate.is_file():
        return False
    if evidence.line_start is None and evidence.line_end is None:
        return True
    start = evidence.line_start or evidence.line_end
    end = evidence.line_end or evidence.line_start
    if start is None or end is None or start < 1 or end < start:
        return False
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            line_count = sum(1 for _ in handle)
        return end <= line_count
    except (OSError, UnicodeError):
        return False


def score_case(
    case: EvaluationCase,
    result: AgentRunResult,
    project_root: Path,
) -> CaseEvaluation:
    report = result.report
    report_text = _report_text(report)
    root_cause_text = _root_cause_text(report)
    reported_files = {_normalized_path(item.file) for item in report.evidence if item.file}

    missing_keywords = [
        keyword
        for keyword in case.root_cause_keywords
        if keyword.lower() not in root_cause_text
    ]
    keyword_hits = len(case.root_cause_keywords) - len(missing_keywords)
    evidence_hits = sum(
        _normalized_path(file) in reported_files for file in case.evidence_files
    )
    observation_map = {item.observation_id: item for item in result.observations}
    grounding_results = [
        evidence_is_grounded(item, observation_map.get(item.observation_id))
        for item in report.evidence
    ]
    grounded_evidence_ids = {
        item.evidence_id
        for item, grounded in zip(report.evidence, grounding_results)
        if grounded
    }
    grounded_rag_files = {
        _normalized_path(item.file)
        for item, grounded in zip(report.evidence, grounding_results)
        if grounded
        and observation_map[item.observation_id].tool_name == "retrieve_docs"
        and item.source_type == "documentation"
    }
    doc_hits = sum(
        _normalized_path(file) in grounded_rag_files for file in case.relevant_docs
    )
    supported_claims = sum(
        bool(item.evidence_ids)
        and all(evidence_id in grounded_evidence_ids for evidence_id in item.evidence_ids)
        for item in report.claims
    )
    provenance_errors = validate_report_provenance(report, result.observations)
    runtime_evidence_count = sum(
        grounded and item.source_type == "runtime" and bool(item.runtime_id)
        for item, grounded in zip(report.evidence, grounding_results)
    )
    citation_results = [
        _citation_is_valid(project_root, item) and grounded
        for item, grounded in zip(report.evidence, grounding_results)
    ]
    valid_citations = sum(citation_results)
    invalid_citations = len(citation_results) - valid_citations
    keyword_rate = _rate(keyword_hits, len(case.root_cause_keywords))
    evidence_rate = _rate(evidence_hits, len(case.evidence_files))
    doc_rate = _rate(doc_hits, len(case.relevant_docs))
    # 没有提交引用不能算“100% 有效”；否则空兜底报告会制造虚假的满分。
    citation_rate = _rate(valid_citations, len(citation_results)) if citation_results else 0.0
    grounded_rate = (
        round(sum(grounding_results) / len(grounding_results), 4)
        if grounding_results
        else 0.0
    )
    claim_rate = (
        round(supported_claims / len(report.claims), 4)
        if report.claims
        else 0.0
    )

    # 通过条件故意保持可解释：根因关键词全中、至少一半核心代码文件命中，
    # 并且报告里所有本地文件引用都真实有效。文档命中单独计分，不作为硬门槛。
    failure_reasons: list[str] = []
    if missing_keywords:
        failure_reasons.append(
            f"missing_root_cause_keywords:{','.join(missing_keywords)}"
        )
    if evidence_rate < 0.5:
        failure_reasons.append("insufficient_evidence_files")
    if invalid_citations:
        failure_reasons.append(f"invalid_citations:{invalid_citations}")
    if grounded_rate < 1.0:
        failure_reasons.append("ungrounded_evidence")
    if claim_rate < 1.0:
        failure_reasons.append("unsupported_claims")
    if provenance_errors:
        failure_reasons.append(f"provenance_violations:{len(provenance_errors)}")
    if case.requires_runtime_evidence and runtime_evidence_count == 0:
        failure_reasons.append("missing_runtime_evidence")
    if result.metrics.stop_reason != "completed":
        failure_reasons.append(f"stop_reason:{result.metrics.stop_reason}")
    passed = not failure_reasons
    scores = CaseScores(
        expected_exception_mentioned=case.expected_exception.lower() in report_text,
        root_cause_keyword_hits=keyword_hits,
        root_cause_keyword_total=len(case.root_cause_keywords),
        root_cause_keyword_rate=keyword_rate,
        evidence_file_hits=evidence_hits,
        evidence_file_total=len(case.evidence_files),
        evidence_file_rate=evidence_rate,
        relevant_doc_hits=doc_hits,
        relevant_doc_total=len(case.relevant_docs),
        relevant_doc_rate=doc_rate,
        valid_citations=valid_citations,
        invalid_citations=invalid_citations,
        citation_validity_rate=citation_rate,
        grounded_evidence_count=sum(grounding_results),
        evidence_total=len(grounding_results),
        evidence_grounded_rate=grounded_rate,
        supported_claim_count=supported_claims,
        claim_total=len(report.claims),
        claim_coverage_rate=claim_rate,
        provenance_violation_count=len(provenance_errors),
        runtime_evidence_count=runtime_evidence_count,
        runtime_evidence_required=case.requires_runtime_evidence,
        failure_reasons=failure_reasons,
        passed=passed,
    )
    return CaseEvaluation(
        case_id=case.case_id,
        question=case.question,
        profile=result.metrics.tool_profile,
        report=report,
        metrics=result.metrics,
        observations=result.observations,
        hypotheses=result.hypotheses,
        validation_errors=result.validation_errors,
        scores=scores,
    )


def load_cases(directory: Path, case_ids: Optional[set[str]] = None) -> list[EvaluationCase]:
    cases = [
        EvaluationCase.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]
    if case_ids is not None:
        cases = [case for case in cases if case.case_id in case_ids]
        missing = case_ids - {case.case_id for case in cases}
        if missing:
            raise ValueError(f"未知评测案例: {', '.join(sorted(missing))}")
    if not cases:
        raise ValueError("没有找到可运行的评测案例")
    return cases


def _average(values: Iterable[float]) -> float:
    values = list(values)
    return round(mean(values), 4) if values else 0.0


def run_evaluation(
    cases: list[EvaluationCase],
    runner: AgentRunner,
    project_root: Path,
    max_steps: int = 8,
) -> EvaluationRun:
    results: list[CaseEvaluation] = []
    for index, case in enumerate(cases, 1):
        print(f"\n=== 评测 {index}/{len(cases)}：{case.case_id} ===")
        results.append(score_case(case, runner(case.question, max_steps), project_root))

    summary = EvaluationSummary(
        case_count=len(results),
        passed_count=sum(result.scores.passed for result in results),
        pass_rate=_rate(sum(result.scores.passed for result in results), len(results)),
        average_root_cause_keyword_rate=_average(
            result.scores.root_cause_keyword_rate for result in results
        ),
        average_evidence_file_rate=_average(
            result.scores.evidence_file_rate for result in results
        ),
        average_relevant_doc_rate=_average(
            result.scores.relevant_doc_rate for result in results
        ),
        average_citation_validity_rate=_average(
            result.scores.citation_validity_rate for result in results
        ),
        average_model_call_count=_average(
            result.metrics.model_call_count for result in results
        ),
        average_tool_call_count=_average(
            result.metrics.tool_call_count for result in results
        ),
        total_duration_ms=round(sum(result.metrics.duration_ms for result in results), 2),
    )
    return EvaluationRun(cases=results, summary=summary)


def save_evaluation(result: EvaluationRun, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
