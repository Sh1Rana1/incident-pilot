"""V9 工具 Profile：同时限制工具集合、运行能力和数据范围。"""

from contextvars import ContextVar, Token
from pathlib import PurePosixPath
from typing import Literal, cast


ToolProfileName = Literal["code_only", "code_rag", "full", "full_runtime"]

CODE_TOOLS = frozenset({"list_files", "search_code", "read_file"})
RAG_TOOLS = frozenset({"retrieve_docs"})
GIT_TOOLS = frozenset({"git_status", "git_diff", "git_log"})
RUNTIME_TOOLS = frozenset({"run_demo_case"})

TOOL_PROFILES: dict[ToolProfileName, frozenset[str]] = {
    "code_only": CODE_TOOLS,
    "code_rag": CODE_TOOLS | RAG_TOOLS,
    "full": CODE_TOOLS | RAG_TOOLS | GIT_TOOLS,
    "full_runtime": CODE_TOOLS | RAG_TOOLS | GIT_TOOLS | RUNTIME_TOOLS,
}

# 普通 --compare 仍保持原来的三组，避免无意增加真实模型和本地执行次数。
STANDARD_EXPERIMENT_PROFILES = ("code_only", "code_rag", "full")

# 文件工具在所有 Markdown 上必须绕经 retrieve_docs。下面的目录是当前 RAG
# 确实建立索引的数据源；其他 Markdown 在实验 Profile 下不会直接暴露。
RAG_ONLY_ROOTS = (
    PurePosixPath("knowledge"),
    PurePosixPath("demo_app/docs"),
)

_ACTIVE_PROFILE: ContextVar[ToolProfileName | None] = ContextVar(
    "incident_pilot_tool_profile",
    default=None,
)


def resolve_tool_profile(name: str) -> tuple[ToolProfileName, frozenset[str]]:
    if name not in TOOL_PROFILES:
        choices = ", ".join(TOOL_PROFILES)
        raise ValueError(f"未知工具 Profile: {name}；可选值: {choices}")
    profile = cast(ToolProfileName, name)
    return profile, TOOL_PROFILES[profile]


def activate_tool_profile(name: str | None) -> Token:
    """在一次工具执行期间激活 Profile，供文件工具实施路径级隔离。"""
    profile = resolve_tool_profile(name)[0] if name is not None else None
    return _ACTIVE_PROFILE.set(profile)


def reset_tool_profile(token: Token) -> None:
    _ACTIVE_PROFILE.reset(token)


def direct_file_access_blocked(relative_path: str) -> bool:
    """已激活实验 Profile 时，Markdown 文档不能由通用文件工具访问。"""
    if _ACTIVE_PROFILE.get() is None:
        return False
    normalized = PurePosixPath(relative_path.replace("\\", "/").lstrip("./"))
    return normalized.suffix.lower() == ".md" or any(
        normalized == root or root in normalized.parents for root in RAG_ONLY_ROOTS
    )
