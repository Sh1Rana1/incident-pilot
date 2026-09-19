"""V14.10 产品化演示：固定事故目录、交互选择和 Markdown 导出。"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from demo_app.run_case import CASES
from models import Evidence, PatchVerificationResult, ToolObservation
from session_store import SessionRecord


ROOT = Path(__file__).resolve().parent
InputFunction = Callable[[str], str]


@dataclass(frozen=True)
class DemoCase:
    case_id: str
    title: str
    log_file: str


DEMO_CASES = (
    DemoCase("missing_user_id", "API 必填字段缺失", "missing_user_id.log"),
    DemoCase("schema_mismatch", "数据库 Schema 不一致", "schema_mismatch.log"),
    DemoCase("connection_leak", "异常路径连接泄漏", "connection_leak.log"),
    DemoCase(
        "documentation_required",
        "外部服务超时契约变化",
        "webhook_timeout_policy.log",
    ),
    DemoCase("async_missing_await", "异步调用遗漏 await", "async_missing_await.log"),
    DemoCase("retry_non_idempotent", "非幂等支付重试", "retry_non_idempotent.log"),
    DemoCase("timezone_mismatch", "时区换算错误", "timezone_mismatch.log"),
    DemoCase("cache_key_version", "缓存 Key 版本不一致", "cache_key_version.log"),
    DemoCase("pagination_off_by_one", "分页边界错误", "pagination_off_by_one.log"),
    DemoCase("config_env_rename", "环境变量改名", "config_env_rename.log"),
    DemoCase("transaction_rollback", "事务未回滚", "transaction_rollback.log"),
    DemoCase(
        "dependency_contract_change",
        "SDK 依赖契约变化",
        "dependency_contract_change.log",
    ),
)
DEMO_CASE_MAP = {item.case_id: item for item in DEMO_CASES}


def validate_demo_catalog(project_root: Path = ROOT) -> None:
    configured = tuple(item.case_id for item in DEMO_CASES)
    if configured != CASES:
        raise ValueError("演示目录必须与 demo_app.run_case.CASES 顺序一致")
    missing = [
        item.log_file
        for item in DEMO_CASES
        if not (project_root / "demo_app" / "logs" / item.log_file).is_file()
    ]
    if missing:
        raise ValueError(f"演示日志不存在: {', '.join(missing)}")


def choose_demo_case(input_fn: InputFunction = input) -> str | None:
    print("\n请选择一个预登记事故：")
    for index, item in enumerate(DEMO_CASES, 1):
        print(f"{index:>2}. {item.title} ({item.case_id})")
    print(" q. 取消")
    while True:
        answer = input_fn("请输入编号：").strip().lower()
        if answer in {"q", "quit", "exit"}:
            return None
        try:
            selected = int(answer)
        except ValueError:
            selected = 0
        if 1 <= selected <= len(DEMO_CASES):
            return DEMO_CASES[selected - 1].case_id
        print(f"请输入 1–{len(DEMO_CASES)} 或 q。")


def load_demo_question(case_id: str, project_root: Path = ROOT) -> str:
    validate_demo_catalog(project_root)
    try:
        item = DEMO_CASE_MAP[case_id]
    except KeyError as exc:
        raise ValueError(f"未知演示案例: {case_id}") from exc
    log_path = project_root / "demo_app" / "logs" / item.log_file
    log_text = log_path.read_text(encoding="utf-8").strip()
    return (
        f"请调查预登记演示事故 {case_id}（{item.title}）。\n"
        "请基于允许访问的代码、文档、Git 或经审批的 Runtime 证据，"
        "区分直接报错点和系统根因，并给出可验证的修复建议。\n\n"
        f"以下是事故日志：\n{log_text}"
    )


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _location(item: Evidence) -> str:
    if item.runtime_id:
        return f"runtime:{item.runtime_id}"
    if item.commit_hash:
        return f"commit:{item.commit_hash}"
    location = item.file or "-"
    if item.line_start is not None:
        location += f":{item.line_start}"
        if item.line_end not in {None, item.line_start}:
            location += f"-{item.line_end}"
    return location


def _observation_sources(item: ToolObservation) -> str:
    locations: list[str] = []
    for source in item.sources:
        if source.runtime_id:
            locations.append(f"runtime:{source.runtime_id}")
        elif source.commit_hash:
            locations.append(f"commit:{source.commit_hash}")
        elif source.file:
            location = source.file
            if source.line_start is not None:
                location += f":{source.line_start}"
                if source.line_end not in {None, source.line_start}:
                    location += f"-{source.line_end}"
            locations.append(location)
    return "<br>".join(_cell(value) for value in locations) or "-"


def _verification_markdown(result: PatchVerificationResult) -> list[str]:
    rows = [
        "## 隔离补丁验证",
        "",
        f"- 状态：`{result.status}`",
        f"- 仅在隔离副本应用：`{result.applied_in_sandbox}`",
        f"- 正式工作区未变化：`{result.workspace_unchanged}`",
        f"- 临时目录已清理：`{result.sandbox_cleaned}`",
        "",
        "| 阶段 | Check | 用途 | 结果 |",
        "|---|---|---|---|",
    ]
    for run in result.check_runs:
        outcome = (
            f"exit={run.exit_code}, expectation={run.expectation_met}, "
            f"success={run.success_criterion_met}"
        )
        rows.append(
            f"| {_cell(run.phase)} | {_cell(run.check_id)} | "
            f"{_cell(run.purpose)} | {_cell(outcome)} |"
        )
    if result.validation_errors:
        rows.extend(["", "验证错误："])
        rows.extend(f"- {_cell(error)}" for error in result.validation_errors)
    return rows


def format_demo_markdown(case_id: str, record: SessionRecord) -> str:
    item = DEMO_CASE_MAP[case_id]
    lines = [
        f"# IncidentPilot 演示报告：{item.title}",
        "",
        f"- Case ID：`{case_id}`",
        f"- 调查 ID：`{record.thread_id}`",
        f"- 状态：`{record.status}`",
        f"- Tool Profile：`{record.tool_profile}`",
        f"- Runtime 已启用：`{record.runtime_tools_enabled}`",
        f"- 更新时间：`{record.updated_at}`",
        "",
        "## 输入事故",
        "",
        "```text",
        record.question,
        "```",
    ]
    if record.result is None:
        lines.extend(["", "## 当前进度", ""])
        if record.pending_review is not None:
            lines.append(record.pending_review.message)
            lines.append("")
            lines.append(
                f"稍后可运行 `python main.py resume {record.thread_id}` 继续。"
            )
        elif record.last_error:
            lines.append(f"运行失败：{record.last_error}")
        else:
            lines.append("调查尚未生成最终报告。")
        return "\n".join(lines).rstrip() + "\n"

    result = record.result
    report = result.report
    lines.extend([
        "",
        "## 诊断结论",
        "",
        f"**摘要：** {report.summary}",
        "",
        f"**根因：** {report.root_cause}",
        "",
        f"**置信度：** `{report.confidence}`",
        "",
        "### Claim–Evidence Ledger",
        "",
        "| Claim | 结论 | Evidence |",
        "|---|---|---|",
    ])
    for claim in report.claims:
        lines.append(
            f"| {_cell(claim.claim_id)} | {_cell(claim.statement)} | "
            f"{_cell(', '.join(claim.evidence_ids))} |"
        )
    lines.extend([
        "",
        "### Evidence",
        "",
        "| Evidence | 类型 | 来源 | Observation | 说明 |",
        "|---|---|---|---|---|",
    ])
    for evidence in report.evidence:
        lines.append(
            f"| {_cell(evidence.evidence_id)} | {_cell(evidence.source_type)} | "
            f"{_cell(_location(evidence))} | {_cell(evidence.observation_id)} | "
            f"{_cell(evidence.description)} |"
        )
    lines.extend(["", "### 修复建议", ""])
    lines.extend(
        f"{index}. {fix}"
        for index, fix in enumerate(report.suggested_fixes, 1)
    )
    lines.extend([
        "",
        "## 调查轨迹",
        "",
        "| Step | Observation | 工具 | 成功 | 参数 | 来源 |",
        "|---:|---|---|---|---|---|",
    ])
    for observation in result.observations:
        arguments = json.dumps(
            observation.arguments, ensure_ascii=False, separators=(",", ":")
        )
        lines.append(
            f"| {observation.step} | {_cell(observation.observation_id)} | "
            f"{_cell(observation.tool_name)} | {observation.ok} | "
            f"`{_cell(arguments)}` | {_observation_sources(observation)} |"
        )
    metrics = result.metrics
    lines.extend([
        "",
        "## 运行指标",
        "",
        f"- 模型调用：{metrics.model_call_count}",
        f"- 工具调用：{metrics.tool_call_count}",
        f"- Token：{metrics.total_token_count}",
        f"- Observation 利用率：{metrics.observation_utilization_rate:.2%}",
        f"- Runtime：{metrics.successful_runtime_call_count}/{metrics.runtime_call_count}",
        f"- 格式修复：`{metrics.format_repair_used}`",
        f"- Fallback：`{metrics.stop_reason != 'completed'}`",
        f"- 计算耗时：{record.compute_duration_ms / 1000:.2f} 秒",
    ])
    if result.patch_proposal is not None:
        proposal = result.patch_proposal
        lines.extend([
            "",
            "## 只读补丁提案",
            "",
            f"- 提案 ID：`{proposal.proposal_id}`",
            f"- 状态：`{proposal.status}`",
            f"- 修改文件：{', '.join(proposal.changed_files) or '无'}",
            f"- 验证 Check：{', '.join(proposal.verification_check_ids) or '无'}",
            "",
            proposal.rationale,
            "",
            "```diff",
            proposal.unified_diff,
            "```",
        ])
    elif result.metrics.patch_requested:
        lines.extend(["", "## 只读补丁提案", "", "补丁提案未生成。"])
        lines.extend(f"- {_cell(error)}" for error in result.patch_validation_errors)
    if result.patch_verification is not None:
        lines.extend(["", *_verification_markdown(result.patch_verification)])
    if result.validation_errors:
        lines.extend(["", "## 调查期间的验证错误", ""])
        lines.extend(f"- {_cell(error)}" for error in result.validation_errors)
    lines.extend([
        "",
        "---",
        "",
        "该报告由 IncidentPilot 生成。补丁提案默认只读；隔离验证不会修改正式工作区。",
    ])
    return "\n".join(lines).rstrip() + "\n"


def resolve_demo_output(
    case_id: str,
    thread_id: str,
    requested: Path | None = None,
    project_root: Path = ROOT,
) -> Path:
    report_root = (project_root / ".incident_reports" / "demos").resolve()
    candidate = (
        report_root / f"demo-{case_id}-{thread_id[:8]}.md"
        if requested is None
        else (requested if requested.is_absolute() else project_root / requested)
    ).resolve()
    try:
        candidate.relative_to(report_root)
    except ValueError as exc:
        raise ValueError("演示报告只能写入 .incident_reports/demos/") from exc
    if candidate.suffix.lower() != ".md":
        raise ValueError("演示报告必须使用 .md 扩展名")
    return candidate


def save_demo_markdown(content: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    except FileExistsError as exc:
        raise FileExistsError(f"拒绝覆盖已有演示报告: {output_path}") from exc
