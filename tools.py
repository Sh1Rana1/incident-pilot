"""Agent 的只读本地工具。使用装饰器注册，结果统一为 ToolResult。"""

from pathlib import Path

from pydantic import Field

from models import StrictModel, ToolResult
from registry import registry
from tool_profiles import direct_file_access_blocked


PROJECT_ROOT = Path(__file__).resolve().parent
MAX_FILE_CHARS = 20_000
MAX_READ_LINES = 30
MAX_SEARCH_MATCHES = 50
MAX_LIST_ITEMS = 200
IGNORED_DIRS = {
    ".git", ".venv", ".incident_cache", ".incident_reports", ".incident_state",
    "evals", "__pycache__",
    "node_modules", "build", "dist", ".pytest_cache", "fixtures", "checks",
}
INTERNAL_ONLY_DIRS = {
    ".incident_cache", ".incident_reports", ".incident_state", "evals", "fixtures", "checks"
}
INTERNAL_ONLY_FILES = {
    "harness.json",
    "harness.py",
    "runtime_tools.py",
    "doctor.py",
    "evaluation.py",
    "llm_judge.py",
    "benchmark.py",
    "experiments.py",
    "run_evals.py",
    "patching.py",
    "patch_verification.py",
}
SENSITIVE_FILES = {"api.env", ".env", ".env.local", ".env.production"}
SEARCHABLE_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}


class ReadFileArgs(StrictModel):
    path: str = Field(description="项目根目录下的相对文件路径")
    start_line: int | None = Field(
        default=None,
        ge=1,
        description="可选的起始行（从 1 开始且包含）；读取整个文件时传 null",
    )
    end_line: int | None = Field(
        default=None,
        ge=1,
        description="可选的结束行（包含）；读取整个文件时传 null",
    )


class SearchCodeArgs(StrictModel):
    query: str = Field(min_length=1, description="要搜索的代码或关键词")


class ListFilesArgs(StrictModel):
    path: str = Field(description="项目根目录下的相对目录；查看根目录时传入点号")
    max_depth: int = Field(ge=1, le=5, description="递归深度，范围 1 到 5；通常使用 3")


def _safe_path(relative_path: str) -> Path:
    path = (PROJECT_ROOT / relative_path).resolve()
    if path != PROJECT_ROOT and PROJECT_ROOT not in path.parents:
        raise ValueError("路径必须位于项目根目录内")
    return path


def _is_ignored(path: Path) -> bool:
    return _is_internal_filename(path) or any(
        part in IGNORED_DIRS for part in path.relative_to(PROJECT_ROOT).parts
    )


def _is_internal_only(path: Path) -> bool:
    return _is_internal_filename(path) or any(
        part in INTERNAL_ONLY_DIRS for part in path.relative_to(PROJECT_ROOT).parts
    )


def _is_internal_filename(path: Path) -> bool:
    return path.name in INTERNAL_ONLY_FILES or (
        path.suffix.lower() == ".py" and path.name.startswith("test_")
    )


def _relative_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _direct_access_blocked(path: Path) -> bool:
    return direct_file_access_blocked(_relative_path(path))


@registry.register(
    name="read_file",
    description=(
        "读取项目内指定 UTF-8 文本文件，返回原始行号。已知目标位置时传入 "
        "start_line/end_line，定向窗口最多 30 行；未知位置时两者传 null。"
    ),
    arguments_model=ReadFileArgs,
)
def read_file(arguments: ReadFileArgs) -> ToolResult:
    file_path = _safe_path(arguments.path)
    if _is_internal_only(file_path):
        return ToolResult.failure("该路径属于评测或内部缓存目录，不能提供给 Agent")
    if file_path.name in SENSITIVE_FILES:
        return ToolResult.failure("出于安全原因，不能读取敏感配置文件", path=arguments.path)
    if _direct_access_blocked(file_path):
        return ToolResult.failure(
            "当前工具 Profile 禁止直接读取知识文档，请使用 retrieve_docs",
            path=arguments.path,
            reason="rag_required_for_path",
        )
    if not file_path.is_file():
        return ToolResult.failure("文件不存在", path=arguments.path)
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult.failure("无法读取二进制或非 UTF-8 文件", path=arguments.path)

    targeted = arguments.start_line is not None or arguments.end_line is not None
    if not targeted:
        truncated = len(content) > MAX_FILE_CHARS
        if truncated:
            content = content[:MAX_FILE_CHARS]
        lines = [
            {"line": number, "content": line}
            for number, line in enumerate(content.splitlines(), 1)
        ]
        returned_characters = len(content)
        actual_start = lines[0]["line"] if lines else None
        actual_end = lines[-1]["line"] if lines else None
    else:
        start_line = arguments.start_line or 1
        end_line = arguments.end_line or start_line + MAX_READ_LINES - 1
        if end_line < start_line:
            return ToolResult.failure(
                "end_line 不能小于 start_line",
                path=arguments.path,
                start_line=start_line,
                end_line=end_line,
            )
        if end_line - start_line + 1 > MAX_READ_LINES:
            return ToolResult.failure(
                f"定向读取单次最多 {MAX_READ_LINES} 行，请缩小范围",
                path=arguments.path,
                start_line=start_line,
                end_line=end_line,
                max_lines=MAX_READ_LINES,
            )
        source_lines = content.splitlines()
        if start_line > len(source_lines):
            return ToolResult.failure(
                "start_line 超出文件总行数",
                path=arguments.path,
                start_line=start_line,
                total_lines=len(source_lines),
            )
        actual_end = min(end_line, len(source_lines))
        selected = source_lines[start_line - 1:actual_end]
        lines = []
        returned_characters = 0
        truncated = False
        for number, line in enumerate(selected, start_line):
            separator_length = int(bool(lines))
            remaining = MAX_FILE_CHARS - returned_characters - separator_length
            if remaining <= 0:
                truncated = True
                break
            if len(line) > remaining:
                line = line[:remaining]
                truncated = True
            lines.append({"line": number, "content": line})
            returned_characters += separator_length + len(line)
            if truncated:
                break
        actual_start = start_line
        actual_end = lines[-1]["line"] if lines else None
    return ToolResult.success(
        {"path": arguments.path, "lines": lines},
        truncated=truncated,
        returned_characters=returned_characters,
        targeted=targeted,
        line_start=actual_start,
        line_end=actual_end,
    )


@registry.register(
    name="search_code",
    description="在项目代码和文本文件中搜索关键词，返回文件、行号和命中内容。",
    arguments_model=SearchCodeArgs,
)
def search_code(arguments: SearchCodeArgs) -> ToolResult:
    matches: list[dict] = []
    truncated = False
    query_lower = arguments.query.lower()
    for file_path in PROJECT_ROOT.rglob("*"):
        if _is_ignored(file_path) or file_path.name in SENSITIVE_FILES:
            continue
        if _direct_access_blocked(file_path):
            continue
        if not file_path.is_file() or file_path.suffix.lower() not in SEARCHABLE_SUFFIXES:
            continue
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(lines, 1):
            if query_lower in line.lower():
                matches.append({
                    "path": file_path.relative_to(PROJECT_ROOT).as_posix(),
                    "line": line_number,
                    "content": line.strip(),
                })
                if len(matches) >= MAX_SEARCH_MATCHES:
                    truncated = True
                    break
        if truncated:
            break
    return ToolResult.success(
        {"query": arguments.query, "matches": matches},
        match_count=len(matches),
        truncated=truncated,
    )


@registry.register(
    name="list_files",
    description="列出项目内的目录和文件。在缺少文件名或搜索关键词时，用它了解项目结构。",
    arguments_model=ListFilesArgs,
)
def list_files(arguments: ListFilesArgs) -> ToolResult:
    start = _safe_path(arguments.path)
    if not start.exists():
        return ToolResult.failure("目录不存在", path=arguments.path)
    if not start.is_dir():
        return ToolResult.failure("指定路径不是目录", path=arguments.path)
    if _direct_access_blocked(start):
        return ToolResult.failure(
            "当前工具 Profile 禁止直接浏览知识文档，请使用 retrieve_docs",
            path=arguments.path,
            reason="rag_required_for_path",
        )

    base_depth = len(start.relative_to(PROJECT_ROOT).parts)
    entries: list[dict] = []
    truncated = False
    for path in sorted(start.rglob("*"), key=lambda item: item.as_posix().lower()):
        if _is_ignored(path) or path.name in SENSITIVE_FILES:
            continue
        if _direct_access_blocked(path):
            continue
        depth = len(path.relative_to(PROJECT_ROOT).parts) - base_depth
        if depth > arguments.max_depth:
            continue
        entries.append({
            "path": path.relative_to(PROJECT_ROOT).as_posix(),
            "type": "directory" if path.is_dir() else "file",
        })
        if len(entries) >= MAX_LIST_ITEMS:
            truncated = True
            break
    return ToolResult.success(
        {"root": arguments.path, "entries": entries},
        item_count=len(entries),
        max_depth=arguments.max_depth,
        truncated=truncated,
    )


# 分模块实现工具，但在导入 tools 时统一触发注册。
import knowledge_tools  # noqa: E402,F401
import git_tools  # noqa: E402,F401
