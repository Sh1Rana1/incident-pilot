"""V8.1.1 多工具 Profile、证据利用率、成本与稳定性实验。"""

import json
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from statistics import mean, pstdev

from evaluation import CaseEvaluation, EvaluationCase, score_case
from models import AgentRunResult, StrictModel
from tool_profiles import resolve_tool_profile


class ProfileSummary(StrictModel):
    profile: str
    case_id: str | None = None
    unique_case_count: int
    runs_per_case: int
    attempt_count: int
    passed_count: int
    pass_rate: float
    average_root_cause_keyword_rate: float
    root_cause_keyword_rate_stddev: float
    average_evidence_file_rate: float
    evidence_file_rate_stddev: float
    average_relevant_doc_rate: float
    relevant_doc_rate_stddev: float
    average_citation_validity_rate: float
    citation_validity_rate_stddev: float
    average_evidence_grounded_rate: float
    evidence_grounded_rate_stddev: float
    average_claim_coverage_rate: float
    claim_coverage_rate_stddev: float
    total_provenance_violations: int
    average_model_call_count: float
    model_call_count_stddev: float
    average_tool_call_count: float
    tool_call_count_stddev: float
    total_repeated_tool_calls: int
    average_confirmed_hypothesis_count: float
    early_stop_count: int
    early_stop_rate: float
    human_review_count: int
    protected_access_attempt_count: int
    average_total_token_count: float
    total_token_count_stddev: float
    average_context_compaction_count: float
    average_observation_utilization_rate: float
    observation_utilization_rate_stddev: float
    total_unreferenced_successful_observations: int
    total_post_confirmation_tool_calls: int
    format_repair_count: int
    synthesis_count: int
    synthesis_rate: float
    fallback_count: int
    fallback_rate: float
    tool_usage_counts: dict[str, int]
    total_duration_ms: float


class ExperimentRun(StrictModel):
    profiles: list[str]
    runs_per_case: int
    attempts: list[CaseEvaluation]
    case_summaries: list[ProfileSummary]
    profile_summaries: list[ProfileSummary]
    overall_summary: ProfileSummary


ExperimentRunner = Callable[[str, int, str], AgentRunResult]


def _rate(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def _average(values: Iterable[float]) -> float:
    values = list(values)
    return round(mean(values), 4) if values else 0.0


def _stddev(values: Iterable[float]) -> float:
    values = list(values)
    return round(pstdev(values), 4) if len(values) > 1 else 0.0


def summarize_attempts(
    attempts: list[CaseEvaluation],
    profile: str,
    unique_case_count: int,
    runs_per_case: int,
    case_id: str | None = None,
) -> ProfileSummary:
    attempt_count = len(attempts)
    passed_count = sum(item.scores.passed for item in attempts)
    root_scores = [item.scores.root_cause_keyword_rate for item in attempts]
    evidence_scores = [item.scores.evidence_file_rate for item in attempts]
    doc_scores = [item.scores.relevant_doc_rate for item in attempts]
    citation_scores = [item.scores.citation_validity_rate for item in attempts]
    grounding_scores = [item.scores.evidence_grounded_rate for item in attempts]
    claim_scores = [item.scores.claim_coverage_rate for item in attempts]
    model_counts = [item.metrics.model_call_count for item in attempts]
    tool_counts = [item.metrics.tool_call_count for item in attempts]
    token_counts = [item.metrics.total_token_count for item in attempts]
    utilization_rates = [
        item.metrics.observation_utilization_rate for item in attempts
    ]
    synthesis_count = sum(item.metrics.synthesis_used for item in attempts)
    early_stop_count = sum(item.metrics.early_stopped for item in attempts)
    fallback_count = sum(item.metrics.stop_reason != "completed" for item in attempts)
    tool_usage = Counter(
        tool_name
        for item in attempts
        for tool_name in item.metrics.tool_names
    )
    return ProfileSummary(
        profile=profile,
        case_id=case_id,
        unique_case_count=unique_case_count,
        runs_per_case=runs_per_case,
        attempt_count=attempt_count,
        passed_count=passed_count,
        pass_rate=_rate(passed_count, attempt_count),
        average_root_cause_keyword_rate=_average(root_scores),
        root_cause_keyword_rate_stddev=_stddev(root_scores),
        average_evidence_file_rate=_average(evidence_scores),
        evidence_file_rate_stddev=_stddev(evidence_scores),
        average_relevant_doc_rate=_average(doc_scores),
        relevant_doc_rate_stddev=_stddev(doc_scores),
        average_citation_validity_rate=_average(citation_scores),
        citation_validity_rate_stddev=_stddev(citation_scores),
        average_evidence_grounded_rate=_average(grounding_scores),
        evidence_grounded_rate_stddev=_stddev(grounding_scores),
        average_claim_coverage_rate=_average(claim_scores),
        claim_coverage_rate_stddev=_stddev(claim_scores),
        total_provenance_violations=sum(
            item.scores.provenance_violation_count for item in attempts
        ),
        average_model_call_count=_average(model_counts),
        model_call_count_stddev=_stddev(model_counts),
        average_tool_call_count=_average(tool_counts),
        tool_call_count_stddev=_stddev(tool_counts),
        total_repeated_tool_calls=sum(
            item.metrics.repeated_tool_call_count for item in attempts
        ),
        average_confirmed_hypothesis_count=_average(
            item.metrics.confirmed_hypothesis_count for item in attempts
        ),
        early_stop_count=early_stop_count,
        early_stop_rate=_rate(early_stop_count, attempt_count),
        human_review_count=sum(item.metrics.human_review_count for item in attempts),
        protected_access_attempt_count=sum(
            item.metrics.protected_access_attempt_count for item in attempts
        ),
        average_total_token_count=_average(token_counts),
        total_token_count_stddev=_stddev(token_counts),
        average_context_compaction_count=_average(
            item.metrics.context_compaction_count for item in attempts
        ),
        average_observation_utilization_rate=_average(utilization_rates),
        observation_utilization_rate_stddev=_stddev(utilization_rates),
        total_unreferenced_successful_observations=sum(
            item.metrics.unreferenced_successful_observation_count
            for item in attempts
        ),
        total_post_confirmation_tool_calls=sum(
            item.metrics.post_confirmation_tool_call_count for item in attempts
        ),
        format_repair_count=sum(item.metrics.format_repair_used for item in attempts),
        synthesis_count=synthesis_count,
        synthesis_rate=_rate(synthesis_count, attempt_count),
        fallback_count=fallback_count,
        fallback_rate=_rate(fallback_count, attempt_count),
        tool_usage_counts=dict(sorted(tool_usage.items())),
        total_duration_ms=round(sum(item.metrics.duration_ms for item in attempts), 2),
    )


def run_experiment(
    cases: list[EvaluationCase],
    runner: ExperimentRunner,
    project_root: Path,
    profiles: list[str],
    runs_per_case: int = 1,
    max_steps: int = 8,
) -> ExperimentRun:
    if not cases:
        raise ValueError("没有可运行的评测案例")
    if runs_per_case < 1:
        raise ValueError("runs_per_case 必须大于等于 1")
    normalized_profiles = [resolve_tool_profile(profile)[0] for profile in profiles]
    if len(set(normalized_profiles)) != len(normalized_profiles):
        raise ValueError("工具 Profile 不能重复")

    attempts: list[CaseEvaluation] = []
    total = len(normalized_profiles) * len(cases) * runs_per_case
    current = 0
    for profile in normalized_profiles:
        for case in cases:
            for run_index in range(1, runs_per_case + 1):
                current += 1
                print(
                    f"\n=== 实验 {current}/{total}：{profile} / "
                    f"{case.case_id} / 第 {run_index} 次 ==="
                )
                result = runner(case.question, max_steps, profile)
                evaluation = score_case(case, result, project_root).model_copy(
                    update={"profile": profile, "run_index": run_index}
                )
                attempts.append(evaluation)

    profile_summaries = [
        summarize_attempts(
            [item for item in attempts if item.profile == profile],
            profile,
            len(cases),
            runs_per_case,
        )
        for profile in normalized_profiles
    ]
    case_summaries = [
        summarize_attempts(
            [
                item
                for item in attempts
                if item.profile == profile and item.case_id == case.case_id
            ],
            profile,
            1,
            runs_per_case,
            case_id=case.case_id,
        )
        for profile in normalized_profiles
        for case in cases
    ]
    overall = summarize_attempts(
        attempts,
        "all",
        len(cases),
        runs_per_case,
    )
    return ExperimentRun(
        profiles=normalized_profiles,
        runs_per_case=runs_per_case,
        attempts=attempts,
        case_summaries=case_summaries,
        profile_summaries=profile_summaries,
        overall_summary=overall,
    )


def save_experiment(result: ExperimentRun, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
