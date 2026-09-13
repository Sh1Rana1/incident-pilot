"""V11 受限运行时基础：预登记 Demo、共享解析器与持久幂等账本。"""

import os
import re
import sqlite3
import subprocess
import sys
from contextvars import ContextVar, Token
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal
from uuid import uuid4

from pydantic import Field

from models import StrictModel, ToolResult
from registry import registry


ROOT = Path(__file__).resolve().parent
MAX_CAPTURE_CHARS = 4000
DemoCaseId = Literal[
    "missing_user_id",
    "schema_mismatch",
    "connection_leak",
    "documentation_required",
]
_RUNTIME_TIMEOUT_SECONDS: ContextVar[int] = ContextVar(
    "incident_pilot_runtime_timeout_seconds",
    default=5,
)
_RUNTIME_EXECUTION_CONTEXT: ContextVar[tuple[str, str] | None] = ContextVar(
    "incident_pilot_runtime_execution_context",
    default=None,
)


class RunDemoCaseArgs(StrictModel):
    case_id: DemoCaseId = Field(
        description="预登记的故障案例 ID；不能传入命令、参数或文件路径"
    )


def activate_runtime_timeout(seconds: int) -> Token:
    return _RUNTIME_TIMEOUT_SECONDS.set(seconds)


def reset_runtime_timeout(token: Token) -> None:
    _RUNTIME_TIMEOUT_SECONDS.reset(token)


def activate_runtime_execution(execution_id: str, database_path: str) -> Token:
    return _RUNTIME_EXECUTION_CONTEXT.set((execution_id, database_path))


def reset_runtime_execution(token: Token) -> None:
    _RUNTIME_EXECUTION_CONTEXT.reset(token)


@contextmanager
def _ledger_connection(database_path: str) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database_path, timeout=10)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_executions (
                execution_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _claim_execution(
    database_path: str,
    execution_id: str,
    case_id: str,
) -> tuple[str, str | None]:
    """原子领取执行权；completed 返回缓存，running 代表结果不确定。"""
    with _ledger_connection(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT case_id, status, result_json FROM runtime_executions "
            "WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO runtime_executions "
                "(execution_id, case_id, status) VALUES (?, ?, 'running')",
                (execution_id, case_id),
            )
            return "execute", None
        existing_case, status, result_json = row
        if existing_case != case_id:
            return "collision", None
        if status == "completed" and result_json:
            return "completed", result_json
        return "indeterminate", None


def _complete_execution(
    database_path: str,
    execution_id: str,
    result: ToolResult,
) -> None:
    with _ledger_connection(database_path) as connection:
        connection.execute(
            """
            UPDATE runtime_executions
            SET status = 'completed', result_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE execution_id = ? AND status = 'running'
            """,
            (result.model_dump_json(), execution_id),
        )


def runtime_excerpt(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    redacted = value.replace(str(ROOT), "<project-root>")
    return redacted[-MAX_CAPTURE_CHARS:]


def runtime_environment() -> dict[str, str]:
    """只继承 Python/Windows 启动所需变量，不把 API 密钥带入子进程。"""
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    }
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return environment


def runtime_exception_type(stderr: str) -> str | None:
    for line in reversed(stderr.splitlines()):
        match = re.match(r"([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))(?::|$)", line.strip())
        if match:
            return match.group(1).rsplit(".", 1)[-1]
    return None


def runtime_exception_message(stderr: str) -> str | None:
    for line in reversed(stderr.splitlines()):
        stripped = line.strip()
        if re.match(r"[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)(?::|$)", stripped):
            return stripped[:500]
    return None


def runtime_traceback_frames(stderr: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for path_text, line_text, function in re.findall(
        r'^\s*File "([^"]+)", line (\d+), in (.+)$', stderr, re.MULTILINE
    ):
        if path_text.startswith("<"):
            continue
        try:
            path = Path(path_text).resolve()
            relative = path.relative_to(ROOT).as_posix()
        except (OSError, ValueError):
            continue
        frames.append({
            "file": relative,
            "line": int(line_text),
            "function": function.strip(),
        })
    return frames[-8:]


def current_runtime_timeout_seconds() -> int:
    return _RUNTIME_TIMEOUT_SECONDS.get()


def begin_runtime_execution(
    subject_id: str,
) -> tuple[str | None, str | None, ToolResult | None]:
    """为任一预登记 Runtime 工具领取幂等执行权。"""
    execution_context = _RUNTIME_EXECUTION_CONTEXT.get()
    if execution_context is None:
        return None, None, None
    execution_id, database_path = execution_context
    claim, cached_result = _claim_execution(database_path, execution_id, subject_id)
    if claim == "completed" and cached_result is not None:
        cached = ToolResult.model_validate_json(cached_result)
        return execution_id, database_path, cached.model_copy(update={
            "meta": {
                **cached.meta,
                "execution_id": execution_id,
                "replayed": True,
            }
        })
    if claim == "collision":
        return execution_id, database_path, ToolResult.failure(
            "运行时执行 ID 与预登记项目不匹配，已拒绝执行",
            execution_id=execution_id,
            reason="runtime_execution_collision",
        )
    if claim == "indeterminate":
        return execution_id, database_path, ToolResult.failure(
            "该运行时操作此前已开始但没有可靠完成记录；为避免重复副作用，"
            "系统不会自动重跑，请新建调查并重新审批。",
            execution_id=execution_id,
            reason="runtime_execution_indeterminate",
        )
    return execution_id, database_path, None


def complete_runtime_execution(
    result: ToolResult,
    execution_id: str | None,
    database_path: str | None,
) -> ToolResult:
    if execution_id is None or database_path is None:
        return result
    result = result.model_copy(update={
        "meta": {
            **result.meta,
            "execution_id": execution_id,
            "replayed": False,
        }
    })
    _complete_execution(database_path, execution_id, result)
    return result


@registry.register(
    name="run_demo_case",
    description=(
        "在当前 Python 虚拟环境中复现一个预登记的 demo_app 故障案例，返回退出码、"
        "标准输出、标准错误、异常类型和系统运行编号。不能执行任意 Shell 命令。"
    ),
    arguments_model=RunDemoCaseArgs,
)
def run_demo_case_tool(arguments: RunDemoCaseArgs) -> ToolResult:
    execution_id, database_path, prior_result = begin_runtime_execution(
        arguments.case_id
    )
    if prior_result is not None:
        return prior_result

    def finalize(result: ToolResult) -> ToolResult:
        return complete_runtime_execution(result, execution_id, database_path)

    timeout_seconds = current_runtime_timeout_seconds()
    run_id = f"runtime-{arguments.case_id}-{uuid4().hex[:12]}"
    argv = [sys.executable, "-m", "demo_app.run_case", arguments.case_id]
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=runtime_environment(),
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return finalize(ToolResult.failure(
            f"预登记案例运行超过 {timeout_seconds} 秒，已终止",
            run_id=run_id,
            case_id=arguments.case_id,
            timeout_seconds=timeout_seconds,
            timed_out=True,
            stdout_excerpt=runtime_excerpt(exc.stdout),
            stderr_excerpt=runtime_excerpt(exc.stderr),
        ))

    raw_stderr = completed.stderr or ""
    stderr = runtime_excerpt(raw_stderr)
    return finalize(ToolResult.success(
        {
            "run_id": run_id,
            "execution_id": execution_id,
            "case_id": arguments.case_id,
            "exit_code": completed.returncode,
            # 关键诊断字段放在长 traceback 之前，确保 Observation 摘要不会
            # 因固定长度截断而丢掉真正的异常与业务栈帧。
            "exception_type": runtime_exception_type(raw_stderr),
            "exception_message": runtime_exception_message(raw_stderr),
            "traceback_frames": runtime_traceback_frames(raw_stderr),
            "timed_out": False,
            "timeout_seconds": timeout_seconds,
            "argv": ["<current-python>", "-m", "demo_app.run_case", arguments.case_id],
            "stdout_excerpt": runtime_excerpt(completed.stdout),
            "stderr_excerpt": stderr,
        }
    ))
