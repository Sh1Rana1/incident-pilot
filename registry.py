"""统一工具注册器：注册、生成 Schema、校验参数和执行工具。"""

import json
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from models import ToolResult
from tool_profiles import activate_tool_profile, reset_tool_profile


ToolFunction = Callable[[BaseModel], ToolResult]


def _strict_json_schema(schema: dict) -> dict:
    """转换为 OpenAI/兼容服务严格工具模式接受的 JSON Schema。"""
    normalized = deepcopy(schema)

    def visit(node) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if isinstance(properties, dict):
                # 严格 Function Calling 要求 required 与 properties 完全一致。
                # 业务上的可选值继续通过 anyOf[..., null] 表达；Pydantic
                # 本地执行仍保留默认值，从而兼容旧调用方省略这些字段。
                node["required"] = list(properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(normalized)
    return normalized


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    arguments_model: type[BaseModel]
    function: ToolFunction


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, *, name: str, description: str, arguments_model: type[BaseModel]):
        """装饰器：把函数和它的参数格式注册到同一个地方。"""
        def decorator(function: ToolFunction) -> ToolFunction:
            if name in self._tools:
                raise ValueError(f"工具重复注册: {name}")
            self._tools[name] = RegisteredTool(name, description, arguments_model, function)
            return function
        return decorator

    def schemas(
        self,
        strict: bool = True,
        allowed_tools: frozenset[str] | set[str] | None = None,
    ) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": (
                        _strict_json_schema(tool.arguments_model.model_json_schema())
                        if strict
                        else tool.arguments_model.model_json_schema()
                    ),
                    "strict": strict,
                },
            }
            for tool in self._tools.values()
            if allowed_tools is None or tool.name in allowed_tools
        ]

    def execute(
        self,
        name: str,
        arguments_json: str,
        allowed_tools: frozenset[str] | set[str] | None = None,
        tool_profile: str | None = None,
    ) -> str:
        """严格校验参数并始终返回 ToolResult JSON。"""
        if allowed_tools is not None and name not in allowed_tools:
            return ToolResult.failure(
                f"当前工具 Profile 不允许调用: {name}",
                tool=name,
                reason="tool_not_allowed",
            ).model_dump_json()
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(f"工具不存在: {name}", tool=name).model_dump_json()
        try:
            arguments = tool.arguments_model.model_validate_json(arguments_json)
            profile_token = activate_tool_profile(tool_profile)
            try:
                result = tool.function(arguments)
            finally:
                reset_tool_profile(profile_token)
        except ValidationError as exc:
            result = ToolResult.failure(
                "工具参数校验失败", tool=name, validation_errors=json.loads(exc.json())
            )
        except (ValueError, OSError) as exc:
            result = ToolResult.failure(str(exc), tool=name)
        except Exception as exc:
            result = ToolResult.failure(
                f"工具发生未预期错误: {type(exc).__name__}: {exc}", tool=name
            )
        return result.model_dump_json()

    def validate_arguments(
        self,
        name: str,
        arguments: dict,
        allowed_tools: frozenset[str] | set[str] | None = None,
    ) -> str | None:
        """只校验已注册工具及参数，不执行工具。"""
        if allowed_tools is not None and name not in allowed_tools:
            return f"当前工具 Profile 不允许调用: {name}"
        tool = self._tools.get(name)
        if tool is None:
            return f"工具不存在: {name}"
        try:
            tool.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in item.get('loc', ())) or 'arguments'}: "
                f"{item.get('msg', 'invalid value')}"
                for item in exc.errors(include_url=False)[:4]
            )
            return f"工具参数校验失败: {details}"
        return None

    def normalize_arguments(
        self,
        name: str,
        arguments: dict,
    ) -> tuple[dict | None, str | None]:
        """按工具参数模型补齐默认值，供动作匹配和审计使用。"""
        tool = self._tools.get(name)
        if tool is None:
            return None, f"工具不存在: {name}"
        try:
            parsed = tool.arguments_model.model_validate(arguments)
        except ValidationError as exc:
            return None, f"工具参数校验失败: {exc.error_count()} 处"
        return parsed.model_dump(mode="json"), None

    def names(self) -> list[str]:
        return list(self._tools)


registry = ToolRegistry()
