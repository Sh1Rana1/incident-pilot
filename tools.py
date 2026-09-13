"""Agent 的只读本地工具。使用装饰器注册，结果统一为 ToolResult。"""

from pathlib import Path

from pydantic import Field

from models import StrictModel, ToolResult
from registry import registry
from tool_profiles import direct_file_access_blocked


PROJECT_ROOT = Path(__file__).resolve().parent
MAX_FILE_CHARS = 20_000
MAX_SEARCH_MATCHES = 50
MAX_LIST_ITEMS = 200
IGNORED_DIRS = {
    ".git", ".venv", ".incident_cache", ".incident_reports", ".incident_state",
    "evals", "__pycache__",
    "node_modules", "build", "dist", ".pytest_cache", "fixtures",
}
INTERNAL_ONLY_DIRS = {
    ".incident_cache", ".incident_reports", ".incident_state", "evals", "fixtures"
}
INTERNAL_ONLY_FILES = {
    "harness.json",
    "evaluation.py",
    "experiments.py",
    "run_evals.py",
    "test_evaluation.py",
    "test_experiments.py",
    "test_demo_app.py",
    "test_runtime_tools.py",
    "test_harness.py",
}
SENSITIVE_FILES = {"api.env", ".env", ".env.local", ".env.production"}
SEARCHABLE_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml"}


class ReadFileArgs(StrictModel):
    path: str = Field(description="项目根目录下的相对文件路径")


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
    return path.name in INTERNAL_ONLY_FILES or any(
        part in IGNORED_DIRS for part in path.relative_to(PROJECT_ROOT).parts
    )


def _is_internal_only(path: Path) -> bool:
    return path.name in INTERNAL_ONLY_FILES or any(
        part in INTERNAL_ONLY_DIRS for part in path.relative_to(PROJECT_ROOT).parts
    )


def _relative_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _direct_access_blocked(path: Path) -> bool:
    return direct_file_access_blocked(_relative_path(path))


@registry.register(
    name="read_file",
    description="读取项目内指定 UTF-8 文本文件，返回带行号的内容。",
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

    truncated = len(content) > MAX_FILE_CHARS
    if truncated:
        content = content[:MAX_FILE_CHARS]
    lines = [{"line": number, "content": line} for number, line in enumerate(content.splitlines(), 1)]
    return ToolResult.success(
        {"path": arguments.path, "lines": lines},
        truncated=truncated,
        returned_characters=len(content),
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
