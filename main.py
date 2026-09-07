"""命令行入口：把结构化报告渲染成人类易读文本。"""

from agent import run_agent
from models import IncidentReport


def format_report(report: IncidentReport) -> str:
    evidence = "\n".join(
        f"{index}. {item.file or '未知文件'}"
        f"{f':{item.line}' if item.line is not None else ''} — {item.description}"
        for index, item in enumerate(report.evidence, 1)
    ) or "无"
    fixes = "\n".join(
        f"{index}. {fix}" for index, fix in enumerate(report.suggested_fixes, 1)
    ) or "无"
    return (
        f"摘要：{report.summary}\n\n"
        f"根因：{report.root_cause}\n\n"
        f"证据：\n{evidence}\n\n"
        f"修复建议：\n{fixes}\n\n"
        f"置信度：{report.confidence}"
    )


def main() -> None:
    print("IncidentPilot V2（输入 exit 退出）")
    while True:
        try:
            question = input("\n请粘贴报错或描述问题：\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return
        if question.lower() in {"exit", "quit"}:
            print("已退出。")
            return
        if not question:
            continue

        try:
            report = run_agent(question)
            print(f"\n=== 最终结论 ===\n{format_report(report)}")
        except Exception as exc:
            print(f"\n运行失败: {exc}")


if __name__ == "__main__":
    main()
