"""IncidentPilot V3 的 LangGraph 状态、节点、路由和图构建。"""

import operator
from typing import Annotated, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from openai import OpenAI
from pydantic import ValidationError
from typing_extensions import TypedDict

from config import AppConfig
from models import IncidentReport
from registry import registry
import tools  # noqa: F401：导入时触发工具注册


SYSTEM_PROMPT = """你是 IncidentPilot，一个代码故障分析 Agent。
你的任务是根据用户给出的报错，在当前项目中搜索和读取代码，找到根因。
先用工具收集证据，不要猜测；不要声称看过没有读取的文件。
最终只能输出 JSON，字段必须是 summary、root_cause、evidence、suggested_fixes、confidence。
evidence 中每项必须包含 source_type、file、line、description；source_type 只能是
code、documentation、git、runtime、unknown；confidence 只能是 low、medium、high。
如果证据不足，不要编造文件或行号，应降低 confidence 并明确说明不能确定。
你只能调查和提出建议，不能修改文件。"""


class AgentState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    step_count: int
    tool_call_count: int
    max_steps: int
    report: Optional[dict]
    validation_error: Optional[str]
    stop_reason: Optional[str]


def response_format(config: AppConfig):
    if config.output_mode == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "incident_report",
                "strict": True,
                "schema": IncidentReport.model_json_schema(),
            },
        }
    if config.output_mode == "json_object":
        return {"type": "json_object"}
    return None


def assistant_message_to_dict(message) -> dict:
    """把 SDK 对象转换为可 checkpoint 的普通字典。"""
    data = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else dict(message)
    data["role"] = "assistant"
    return data


def route_after_model(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if last_message.get("tool_calls"):
        if state["step_count"] >= state["max_steps"]:
            return "build_fallback"
        return "execute_tools"
    return "validate_report"


def route_after_validation(state: AgentState) -> str:
    if state.get("report") is not None:
        return "end"
    if state["step_count"] >= state["max_steps"]:
        return "build_fallback"
    return "call_model"


def build_agent_graph(client: OpenAI, config: AppConfig, checkpointer: Optional[InMemorySaver] = None):
    """使用依赖注入构建图，便于真实运行和模拟测试。"""

    def call_model(state: AgentState) -> dict:
        step = state["step_count"] + 1
        print(f"\n--- Agent 第 {step} 步 ---")
        request = {
            "model": config.model,
            "messages": state["messages"],
            "tools": registry.schemas(strict=config.strict_tools),
            "tool_choice": "auto",
        }
        output_format = response_format(config)
        if output_format is not None:
            request["response_format"] = output_format
        response = client.chat.completions.create(**request)
        return {
            "messages": [assistant_message_to_dict(response.choices[0].message)],
            "step_count": step,
            "validation_error": None,
        }

    def execute_tools(state: AgentState) -> dict:
        tool_messages: list[dict] = []
        calls = state["messages"][-1].get("tool_calls", [])
        for tool_call in calls:
            function = tool_call["function"]
            name, arguments = function["name"], function["arguments"]
            print(f"调用工具: {name}({arguments})")
            result = registry.execute(name, arguments)
            print(f"工具结果: {result[:500]}")
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": result,
            })
        return {
            "messages": tool_messages,
            "tool_call_count": state["tool_call_count"] + len(calls),
        }

    def validate_report(state: AgentState) -> dict:
        content = state["messages"][-1].get("content")
        if not content:
            error = "模型没有返回最终报告"
        else:
            try:
                report = IncidentReport.model_validate_json(content)
                return {
                    "report": report.model_dump(),
                    "validation_error": None,
                    "stop_reason": "completed",
                }
            except ValidationError as exc:
                error = f"最终报告有 {exc.error_count()} 处格式错误"
        return {
            "messages": [{
                "role": "user",
                "content": f"{error}。请根据已有证据重新输出，并且只输出完整 JSON 报告。",
            }],
            "validation_error": error,
        }

    def build_fallback(state: AgentState) -> dict:
        report = IncidentReport(
            summary="调查达到最大步数，尚未完成。",
            root_cause="现有证据不足，无法确定根因。",
            evidence=[],
            suggested_fixes=["提供更完整的 traceback，或提高允许的调查步数。"],
            confidence="low",
        )
        return {"report": report.model_dump(), "stop_reason": "max_steps"}

    builder = StateGraph(AgentState)
    builder.add_node("call_model", call_model)
    builder.add_node("execute_tools", execute_tools)
    builder.add_node("validate_report", validate_report)
    builder.add_node("build_fallback", build_fallback)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", route_after_model, {
        "execute_tools": "execute_tools",
        "validate_report": "validate_report",
        "build_fallback": "build_fallback",
    })
    builder.add_edge("execute_tools", "call_model")
    builder.add_conditional_edges("validate_report", route_after_validation, {
        "call_model": "call_model",
        "end": END,
        "build_fallback": "build_fallback",
    })
    builder.add_edge("build_fallback", END)
    return builder.compile(checkpointer=checkpointer)
