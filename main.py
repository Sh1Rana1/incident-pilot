"""V11 命令行入口：持久会话、当场审批与 Safe Test Harness。"""

import argparse
import sys
from collections.abc import Callable

from agent import run_agent
from doctor import print_doctor_report, run_doctor
from models import HumanReviewRequest, IncidentMemory, IncidentReport
from session_agent import resume_session, start_session
from session_store import SessionRecord, SessionStore


InputFunction = Callable[[str], str]
CLI_PREFIX = r".\.venv\Scripts\python.exe main.py"


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
        if item.runtime_id:
            return f"runtime {item.runtime_id}"
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
    if request.reason == "runtime_execution":
        choices = {
            "1": "approve", "2": "deny", "3": "cancel",
            "approve": "approve", "deny": "deny", "cancel": "cancel",
        }
        prompt = "选择 1批准本次运行 / 2拒绝本次运行 / 3取消调查："
    else:
        choices = {
            "1": "continue", "2": "summarize", "3": "cancel",
            "continue": "continue", "summarize": "summarize", "cancel": "cancel",
        }
        prompt = "选择 1继续调查 / 2立即总结 / 3取消："
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in choices:
            return choices[answer]
        print("请输入 1、2 或 3。")


def _print_session(record: SessionRecord) -> None:
    """显示持久化会话，不向用户暴露 SQLite 内部细节。"""
    print(f"\n调查 ID：{record.thread_id}")
    print(f"状态：{record.status}")
    print(f"已用计算时间：{record.compute_duration_ms / 1000:.2f} 秒")
    if record.recalled_memory_ids:
        print("已召回历史线索：" + ", ".join(record.recalled_memory_ids))
    if record.result is not None:
        print(f"\n=== 最终结论 ===\n{format_report(record.result.report)}")
        metrics = record.result.metrics
        print(
            "\n运行指标："
            f"模型 {metrics.model_call_count} 次，"
            f"工具 {metrics.tool_call_count} 次，"
            f"Runtime {metrics.successful_runtime_call_count}/"
            f"{metrics.runtime_call_count} 次成功，"
            f"安全重放 {metrics.runtime_replay_count} 次。"
        )
    elif record.pending_review is not None:
        print(f"等待操作：{record.pending_review.message}")
        print(f"稍后继续：{CLI_PREFIX} resume {record.thread_id}")
    elif record.last_error:
        print(f"失败原因：{record.last_error}")


def _legacy_main() -> None:
    """保留 V9 的单进程使用方式，避免破坏原有习惯和调用方。"""
    print("IncidentPilot V11 · Safe Test Harness LangGraph（输入 exit 退出）")
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
                tool_profile="full_runtime",
                human_review=True,
                review_handler=request_human_review,
            )
            print(f"\n=== 最终结论 ===\n{format_report(report)}")
        except Exception as exc:
            print(f"\n运行失败: {exc}")


def _print_memory_candidate(store: SessionStore, record: SessionRecord) -> None:
    candidate = store.get_memory_for_thread(record.thread_id)
    if candidate is not None and candidate.status == "pending":
        print(
            "\n已生成待审批事故记忆："
            f"{candidate.memory_id}\n"
            f"审批：{CLI_PREFIX} memory approve {candidate.memory_id}"
        )


def _continue_pending_reviews(
    store: SessionStore,
    record: SessionRecord,
    input_fn: InputFunction = input,
) -> SessionRecord:
    """在当前进程处理连续 interrupt；终端中断后仍可手工 resume。"""
    while record.pending_review is not None:
        try:
            action = request_human_review(record.pending_review, input_fn=input_fn)
        except (EOFError, KeyboardInterrupt):
            print("\n审批尚未处理，调查已安全保存。")
            return record
        record = resume_session(store, record.thread_id, action)
    return record


def _new_session(detach: bool = False) -> None:
    question = read_multiline_question()
    if not question:
        print("未提供问题，已取消。")
        return
    with SessionStore() as store:
        record = start_session(store, question)
        if not detach:
            record = _continue_pending_reviews(store, record)
        _print_session(record)
        _print_memory_candidate(store, record)


def _list_sessions(limit: int) -> None:
    with SessionStore() as store:
        records = store.list(limit)
    if not records:
        print("还没有持久化调查。")
        return
    print("最近调查：")
    for record in records:
        question = record.question.splitlines()[0][:48]
        print(
            f"- {record.thread_id}  {record.status:<30} "
            f"{record.updated_at}  {question}"
        )


def _show_session(thread_id: str) -> None:
    with SessionStore() as store:
        record = store.get(thread_id)
    print(f"问题：{record.question}")
    print(f"创建时间：{record.created_at}")
    print(f"更新时间：{record.updated_at}")
    _print_session(record)


def _resume_session(thread_id: str) -> None:
    # 先本地读取审批点；用户做出决定后才创建模型客户端。若恢复后又
    # 遇到 interrupt，则继续在当前终端询问，不要求再次复制 ID。
    with SessionStore() as store:
        record = store.get(thread_id)
        if record.pending_review is None:
            raise ValueError(f"会话当前不需要人工确认：{record.status}")
        record = _continue_pending_reviews(store, record)
        _print_session(record)
        _print_memory_candidate(store, record)


def _doctor_command() -> bool:
    report = run_doctor()
    print_doctor_report(report)
    return report.ok


def _print_memory(memory: IncidentMemory, score: float | None = None) -> None:
    score_text = f"  相似度={score:.3f}" if score is not None else ""
    print(f"\n{memory.memory_id}  [{memory.status}]{score_text}")
    print(f"来源调查：{memory.source_thread_id}")
    print(f"历史根因：{memory.root_cause}")
    print(f"历史修复：{'; '.join(memory.resolution) or '未记录'}")
    print(f"标签：{', '.join(memory.exception_types + memory.symbols + memory.files) or '无'}")


def _memory_command(args: argparse.Namespace) -> None:
    with SessionStore() as store:
        if args.memory_command == "list":
            memories = store.list_memories(status=args.status, limit=args.limit)
            if not memories:
                print("没有符合条件的事故记忆。")
            for memory in memories:
                _print_memory(memory)
        elif args.memory_command == "search":
            matches = store.recall_memories(" ".join(args.query), limit=args.limit)
            if not matches:
                print("没有找到已批准的相似事故。")
            for match in matches:
                _print_memory(match.memory, match.score)
        elif args.memory_command in {"approve", "reject"}:
            status = "approved" if args.memory_command == "approve" else "rejected"
            memory = store.set_memory_status(args.memory_id, status)
            print(f"记忆 {memory.memory_id} 已更新为 {memory.status}。")
        elif args.memory_command == "forget":
            store.delete_memory(args.memory_id)
            print(f"记忆 {args.memory_id} 已删除，不可恢复。")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IncidentPilot V11 Safe Test Harness")
    commands = parser.add_subparsers(dest="command", required=True)
    new_parser = commands.add_parser("new", help="创建调查并当场处理审批")
    new_parser.add_argument(
        "--detach",
        action="store_true",
        help="遇到审批时保存并退出，稍后手工 resume",
    )
    list_parser = commands.add_parser("list", help="列出最近调查")
    list_parser.add_argument("--limit", type=int, default=20)
    show_parser = commands.add_parser("show", help="查看调查状态或结果")
    show_parser.add_argument("thread_id")
    resume_parser = commands.add_parser("resume", help="审批并恢复中断的调查")
    resume_parser.add_argument("thread_id")
    commands.add_parser("doctor", help="检查依赖、api.env 和本地状态库，不调用模型")
    memory_parser = commands.add_parser("memory", help="管理长期事故记忆")
    memory_commands = memory_parser.add_subparsers(
        dest="memory_command", required=True
    )
    memory_list = memory_commands.add_parser("list", help="列出记忆")
    memory_list.add_argument(
        "--status", choices=["pending", "approved", "rejected"], default=None
    )
    memory_list.add_argument("--limit", type=int, default=50)
    memory_search = memory_commands.add_parser("search", help="搜索已批准记忆")
    memory_search.add_argument("query", nargs="+")
    memory_search.add_argument("--limit", type=int, default=3)
    for action in ("approve", "reject", "forget"):
        action_parser = memory_commands.add_parser(action)
        action_parser.add_argument("memory_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    """无参数保留传统模式；显式子命令使用 V11 持久化入口。"""
    args_list = [] if argv is None else argv
    if not args_list:
        _legacy_main()
        return 0
    args = _build_parser().parse_args(args_list)
    try:
        if args.command == "new":
            _new_session(detach=args.detach)
        elif args.command == "list":
            if args.limit < 1:
                raise ValueError("--limit 必须大于等于 1")
            _list_sessions(args.limit)
        elif args.command == "show":
            _show_session(args.thread_id)
        elif args.command == "resume":
            _resume_session(args.thread_id)
        elif args.command == "doctor":
            return 0 if _doctor_command() else 1
        elif args.command == "memory":
            if getattr(args, "limit", 1) < 1:
                raise ValueError("--limit 必须大于等于 1")
            _memory_command(args)
    except Exception as exc:
        print(f"\n操作失败: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
