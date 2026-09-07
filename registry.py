"""统一工具注册器：注册、生成 Schema、校验参数和执行工具。"""

import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from models import ToolResult


ToolFunction = Callable[[BaseModel], ToolResult]


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

    def schemas(self, strict: bool = True) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.arguments_model.model_json_schema(),
                    "strict": strict,
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments_json: str) -> str:
        """严格校验参数并始终返回 ToolResult JSON。"""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(f"工具不存在: {name}", tool=name).model_dump_json()
        try:
            arguments = tool.arguments_model.model_validate_json(arguments_json)
            result = tool.function(arguments)
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

    def names(self) -> list[str]:
        return list(self._tools)


registry = ToolRegistry()
