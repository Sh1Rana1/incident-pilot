"""V2 的统一数据模型：工具结果与最终故障报告。"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolResult(StrictModel):
    ok: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def success(cls, data: Any, **meta: Any) -> "ToolResult":
        return cls(ok=True, data=data, error=None, meta=meta)

    @classmethod
    def failure(cls, error: str, **meta: Any) -> "ToolResult":
        return cls(ok=False, data=None, error=error, meta=meta)


class Evidence(StrictModel):
    file: str = Field(description="证据所在的项目相对路径；未知时填空字符串")
    line: Optional[int] = Field(description="证据行号；无法确定时填 null")
    description: str = Field(description="这条证据说明了什么")


class IncidentReport(StrictModel):
    summary: str = Field(description="一句话概括调查结果")
    root_cause: str = Field(description="根因；证据不足时明确说明尚不能确定")
    evidence: list[Evidence] = Field(description="支持结论的证据列表")
    suggested_fixes: list[str] = Field(description="建议的修复步骤")
    confidence: Literal["low", "medium", "high"]
