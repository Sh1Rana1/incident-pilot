"""知识库检索工具。"""

from pydantic import Field

from models import StrictModel, ToolResult
from registry import registry
from retrieval import LocalDocumentIndex
from tools import PROJECT_ROOT


class RetrieveDocsArgs(StrictModel):
    query: str = Field(min_length=1, description="要在项目知识库中检索的问题或关键词")
    top_k: int = Field(ge=1, le=5, description="返回最相关的片段数量，范围 1 到 5")


@registry.register(
    name="retrieve_docs",
    description=(
        "检索 knowledge 和 demo_app/docs 中的项目文档。适合查询数据库约定、API 规范和历史排障经验；"
        "返回可引用的来源、章节、起始行和相关度。"
    ),
    arguments_model=RetrieveDocsArgs,
)
def retrieve_docs(arguments: RetrieveDocsArgs) -> ToolResult:
    results, cache_hit, chunk_count = LocalDocumentIndex(PROJECT_ROOT).search(
        arguments.query, arguments.top_k
    )
    return ToolResult.success(
        {"query": arguments.query, "chunks": results},
        returned_count=len(results),
        indexed_chunk_count=chunk_count,
        cache_hit=cache_hit,
        retrieval_method="local_feature_hashing_cosine",
    )
