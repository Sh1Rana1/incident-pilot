"""命令行入口：把结构化报告渲染成人类易读文本。"""

from collections.abc import Callable

from agent import run_agent
from models import HumanReviewRequest, IncidentReport


InputFunction = Callable[[str], str]


def read_multiline_question(input_fn: InputFunction = input) -> str | None:
    """连续读取多行；空行提交，EOF 提交已有内容或退出。"""
    print("\n请粘贴报错或描述问题，完成后再按一次 Enter 提交：")
    lines: list[str] = []
    while True:
        try:
            line = input_fn("> " if not lines else "| ")
        except EOFError:
            return "\n".join(lines).strip() or None

        if not line.strip():
            return "\n".join(lines).strip() if lines else ""
        lines.append(line.rstrip())


def format_report(report: IncidentReport) -> str:
    def evidence_location(item) -> str:
        if item.commit_hash:
            return f"commit {item.commit_hash}"
        location = item.file or "无文件"
        if item.line_start is not None:
            location += f":{item.line_start}"
            if item.line_end is not None and item.line_end != item.line_start:
                location += f"-{item.line_end}"
        return location

    evidence = "\n".join(
        f"{index}. {item.evidence_id} [{item.source_type}] "
        f"{evidence_location(item)} ({item.observation_id}) — {item.description}"
        for index, item in enumerate(report.evidence, 1)
    ) or "无"
    claims = "\n".join(
        f"{index}. {item.claim_id}: {item.statement} "
        f"[证据: {', '.join(item.evidence_ids)}]"
        for index, item in enumerate(report.claims, 1)
    ) or "无"
    fixes = "\n".join(
        f"{index}. {fix}" for index, fix in enumerate(report.suggested_fixes, 1)
    ) or "无"
    return (
        f"摘要：{report.summary}\n\n"
        f"根因：{report.root_cause}\n\n"
        f"诊断结论：\n{claims}\n\n"
        f"证据：\n{evidence}\n\n"
        f"修复建议：\n{fixes}\n\n"
        f"置信度：{report.confidence}"
    )


def request_human_review(
    request: HumanReviewRequest,
    input_fn: InputFunction = input,
) -> str:
    """把 LangGraph interrupt 渲染成一个最小人工决策门。"""
    print("\n=== 需要人工确认 ===")
    print(request.message)
    print(
        f"当前模型调用 {request.model_call_count} 次，"
        f"工具调用 {request.tool_call_count} 次。"
    )
    confirmed = [
        item for item in request.hypotheses if item.status == "confirmed"
    ]
    if confirmed:
        print("当前已确认假设：")
        for item in confirmed:
            print(f"- {item.hypothesis_id}: {item.statement} ({item.confidence:.0%})")
    choices = {
        "1": "continue",
        "2": "summarize",
        "3": "cancel",
        "continue": "continue",
        "summarize": "summarize",
        "cancel": "cancel",
    }
    while True:
        answer = input_fn("选择 1继续调查 / 2立即总结 / 3取消：").strip().lower()
        if answer in choices:
            return choices[answer]
        print("请输入 1、2 或 3。")


def main() -> None:
    print("IncidentPilot V8.1.1 · Evidence-Preserving LangGraph（输入 exit 退出）")
    while True:
        try:
            question = read_multiline_question()
        except KeyboardInterrupt:
            print("\n已退出。")
            return
        if question is None:
            print("\n已退出。")
            return
        if question.lower() in {"exit", "quit"}:
            print("已退出。")
            return
        if not question:
            continue

        try:
            report = run_agent(
                question,
                human_review=True,
                review_handler=request_human_review,
            )
            print(f"\n=== 最终结论 ===\n{format_report(report)}")
        except Exception as exc:
            print(f"\n运行失败: {exc}")


if __name__ == "__main__":
    main()
