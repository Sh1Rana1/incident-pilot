"""运行真实模型的 V12.1.1 Runtime、Memory、成本与稳定性实验。"""

import argparse
from datetime import datetime
from pathlib import Path

from agent import run_agent_detailed
from evaluation import load_cases
from experiments import ExperimentRun, run_experiment, save_experiment
from tool_profiles import STANDARD_EXPERIMENT_PROFILES, TOOL_PROFILES


ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_DIR = ROOT / "demo_app" / "evals"
DEFAULT_OUTPUT_DIR = ROOT / ".incident_reports"
MAX_UNCONFIRMED_INVESTIGATIONS = 3


def enforce_experiment_cost_guard(
    investigation_count: int,
    confirmed: bool,
) -> None:
    if investigation_count > MAX_UNCONFIRMED_INVESTIGATIONS and not confirmed:
        raise SystemExit(
            f"费用保护：本次将运行 {investigation_count} 次 Agent 调查，"
            f"超过免确认上限 {MAX_UNCONFIRMED_INVESTIGATIONS}。请先用 --case 缩小范围；"
            "确实需要完整实验时显式追加 --yes。"
        )


def format_summary(result: ExperimentRun) -> str:
    rows = [
        "逐次结果",
        "Profile     案例                     次数  通过  根因  代码  文档  引用  落地 Claim 违规 假设 早停 利用 压缩  模型  工具 运行 Token",
        "-" * 151,
    ]
    for item in result.attempts:
        rows.append(
            f"{item.profile:<11} {item.case_id:<24} {item.run_index:>4}  "
            f"{'是' if item.scores.passed else '否':<4} "
            f"{item.scores.root_cause_keyword_rate:>4.0%} "
            f"{item.scores.evidence_file_rate:>5.0%} "
            f"{item.scores.relevant_doc_rate:>5.0%} "
            f"{item.scores.citation_validity_rate:>5.0%} "
            f"{item.scores.evidence_grounded_rate:>5.0%} "
            f"{item.scores.claim_coverage_rate:>5.0%} "
            f"{item.scores.provenance_violation_count:>4} "
            f"{item.metrics.confirmed_hypothesis_count:>4} "
            f"{'是' if item.metrics.early_stopped else '否':>4} "
            f"{item.metrics.observation_utilization_rate:>4.0%} "
            f"{item.metrics.context_compaction_count:>4} "
            f"{item.metrics.model_call_count:>5} "
            f"{item.metrics.tool_call_count:>5} "
            f"{item.metrics.runtime_call_count:>4} "
            f"{item.metrics.total_token_count:>5}"
        )
    failures = [item for item in result.attempts if item.scores.failure_reasons]
    if failures:
        rows.extend(["", "失败原因"])
        for item in failures:
            rows.append(
                f"- {item.profile} / {item.case_id} / 第 {item.run_index} 次："
                f"{'; '.join(item.scores.failure_reasons)}"
            )
            rows.extend(
                f"  报告验证：{error}" for error in item.validation_errors
            )
    rows.extend(["", "Profile 对照", "Profile      运行  通过率  根因  代码  文档  引用  落地 Claim 违规 假设 早停 利用 压缩  模型±σ       工具±σ       Token±σ"])
    rows.append("-" * 147)
    for summary in result.profile_summaries:
        rows.append(
            f"{summary.profile:<12} {summary.attempt_count:>4} "
            f"{summary.pass_rate:>7.0%} "
            f"{summary.average_root_cause_keyword_rate:>5.0%} "
            f"{summary.average_evidence_file_rate:>5.0%} "
            f"{summary.average_relevant_doc_rate:>5.0%} "
            f"{summary.average_citation_validity_rate:>5.0%} "
            f"{summary.average_evidence_grounded_rate:>5.0%} "
            f"{summary.average_claim_coverage_rate:>5.0%} "
            f"{summary.total_provenance_violations:>4} "
            f"{summary.average_confirmed_hypothesis_count:>4.1f} "
            f"{summary.early_stop_rate:>4.0%} "
            f"{summary.average_observation_utilization_rate:>4.0%} "
            f"{summary.average_context_compaction_count:>4.1f} "
            f"{summary.average_model_call_count:>5.2f}±{summary.model_call_count_stddev:<4.2f} "
            f"{summary.average_tool_call_count:>5.2f}±{summary.tool_call_count_stddev:<4.2f} "
            f"{summary.average_total_token_count:>5.0f}±{summary.total_token_count_stddev:<4.0f}"
        )
    if result.runs_per_case > 1:
        rows.extend([
            "",
            "按案例稳定性（同一道题的波动）",
            "Profile      案例                     通过率  根因±σ       模型±σ       工具±σ",
            "-" * 92,
        ])
        for summary in result.case_summaries:
            rows.append(
                f"{summary.profile:<12} {summary.case_id or '':<24} "
                f"{summary.pass_rate:>7.0%} "
                f"{summary.average_root_cause_keyword_rate:>5.0%}±"
                f"{summary.root_cause_keyword_rate_stddev:<4.2f} "
                f"{summary.average_model_call_count:>5.2f}±"
                f"{summary.model_call_count_stddev:<4.2f} "
                f"{summary.average_tool_call_count:>5.2f}±"
                f"{summary.tool_call_count_stddev:<4.2f}"
            )
    overall = result.overall_summary
    rows.extend([
        "-" * 104,
        f"总计：{overall.passed_count}/{overall.attempt_count} 通过 "
        f"({overall.pass_rate:.0%})；重复工具调用 {overall.total_repeated_tool_calls} 次；"
        f"格式修复 {overall.format_repair_count} 次；最终兜底 {overall.fallback_count} 次；"
        f"未引用成功 Observation {overall.total_unreferenced_successful_observations} 个；"
        f"确认后工具调用 {overall.total_post_confirmation_tool_calls} 次；"
        f"Runtime {overall.successful_runtime_calls}/{overall.total_runtime_calls} 次成功，"
        f"超时 {overall.runtime_timeout_count} 次，"
        f"安全重放 {overall.runtime_replay_count} 次；"
        f"历史记忆召回 {overall.total_recalled_memories} 条；"
        f"人工确认 {overall.human_review_count} 次；总耗时 {overall.total_duration_ms / 1000:.2f} 秒",
    ])
    return "\n".join(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 IncidentPilot V12.1.1 Runtime/Memory 与稳定性实验（会调用真实模型）"
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="只运行指定 case_id；可以重复提供",
    )
    parser.add_argument("--max-steps", type=int, default=8)
    profile_group = parser.add_mutually_exclusive_group()
    profile_group.add_argument(
        "--profile",
        action="append",
        choices=list(TOOL_PROFILES),
        dest="profiles",
        help="工具 Profile；可重复提供，默认 full",
    )
    profile_group.add_argument(
        "--compare",
        action="store_true",
        help="依次运行 code_only、code_rag、full 三组对照实验",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="每个 Profile 的每个案例重复次数，范围 1 到 10",
    )
    parser.add_argument("--output", type=Path, help="自定义 JSON 报告路径")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认运行超过 3 次 Agent 调查的高费用实验",
    )
    parser.add_argument(
        "--allow-runtime",
        action="store_true",
        help="明确允许 full_runtime Profile 执行预登记 Demo Case",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    if arguments.max_steps < 1:
        raise SystemExit("--max-steps 必须大于等于 1")
    if not 1 <= arguments.runs <= 10:
        raise SystemExit("--runs 必须在 1 到 10 之间")
    cases = load_cases(
        DEFAULT_CASES_DIR,
        set(arguments.case_ids) if arguments.case_ids else None,
    )
    profiles = (
        list(STANDARD_EXPERIMENT_PROFILES)
        if arguments.compare
        else (arguments.profiles or ["full"])
    )
    if "full_runtime" in profiles and not arguments.allow_runtime:
        raise SystemExit(
            "运行 full_runtime Profile 必须显式添加说明执行权限：追加 --allow-runtime。"
        )
    investigation_count = len(profiles) * len(cases) * arguments.runs
    print(
        f"将运行 {investigation_count} 次 Agent 调查："
        f"{len(profiles)} 个 Profile × {len(cases)} 个案例 × {arguments.runs} 次。"
    )
    enforce_experiment_cost_guard(investigation_count, arguments.yes)

    def runner(question: str, max_steps: int, profile: str):
        return run_agent_detailed(
            question,
            max_steps=max_steps,
            tool_profile=profile,
            allow_runtime_execution=arguments.allow_runtime,
        )

    result = run_experiment(
        cases,
        runner,
        ROOT,
        profiles,
        arguments.runs,
        arguments.max_steps,
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = arguments.output or DEFAULT_OUTPUT_DIR / f"eval-{timestamp}.json"
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    save_experiment(result, output_path)
    print(f"\n{format_summary(result)}")
    print(f"\n完整 JSON 报告：{output_path}")


if __name__ == "__main__":
    main()
