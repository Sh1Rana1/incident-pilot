"""固定参数、只读、无 shell 的 Git 调查工具。"""

import subprocess

from pydantic import Field

from models import StrictModel, ToolResult
from registry import registry
from tools import MAX_FILE_CHARS, PROJECT_ROOT, SENSITIVE_FILES, _is_internal_only, _safe_path


GIT_TIMEOUT_SECONDS = 8


class EmptyArgs(StrictModel):
    pass


class GitDiffArgs(StrictModel):
    path: str = Field(description="要查看差异的项目相对路径；全部文件使用点号")


class GitLogArgs(StrictModel):
    limit: int = Field(ge=1, le=20, description="返回最近提交的数量，范围 1 到 20")


def _run_git(arguments: list[str]) -> ToolResult:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except FileNotFoundError:
        return ToolResult.failure("系统中没有找到 Git")
    except subprocess.TimeoutExpired:
        return ToolResult.failure("Git 命令执行超时", timeout_seconds=GIT_TIMEOUT_SECONDS)

    output = completed.stdout.strip()
    error = completed.stderr.strip()
    if completed.returncode != 0:
        return ToolResult.failure(
            error or "Git 命令执行失败", return_code=completed.returncode
        )
    truncated = len(output) > MAX_FILE_CHARS
    return ToolResult.success(
        {"output": output[:MAX_FILE_CHARS]},
        return_code=completed.returncode,
        truncated=truncated,
    )


@registry.register(
    name="git_status",
    description="只读查看当前 Git 分支和工作区变更，不修改仓库。",
    arguments_model=EmptyArgs,
)
def git_status(arguments: EmptyArgs) -> ToolResult:
    return _run_git(["status", "--short", "--branch", "--untracked-files=all"])


@registry.register(
    name="git_diff",
    description="只读查看工作区中指定文件或目录的未提交差异。",
    arguments_model=GitDiffArgs,
)
def git_diff(arguments: GitDiffArgs) -> ToolResult:
    path = _safe_path(arguments.path)
    if _is_internal_only(path):
        return ToolResult.failure("不能查看评测答案或内部缓存目录的差异")
    if path.name in SENSITIVE_FILES:
        return ToolResult.failure("出于安全原因，不能查看敏感配置文件的差异")
    relative = path.relative_to(PROJECT_ROOT).as_posix() or "."
    return _run_git(["diff", "--no-ext-diff", "--unified=3", "--", relative])


@registry.register(
    name="git_log",
    description="只读查看最近的 Git 提交哈希、作者、时间和提交信息。",
    arguments_model=GitLogArgs,
)
def git_log(arguments: GitLogArgs) -> ToolResult:
    return _run_git([
        "log",
        f"-{arguments.limit}",
        "--no-decorate",
        "--date=iso-strict",
        "--pretty=format:%H%x09%an%x09%ad%x09%s",
    ])
