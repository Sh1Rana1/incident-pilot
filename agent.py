"""V2 Agent Loop：统一工具注册与结构化最终输出。"""

from pathlib import Path

from openai import OpenAI
from pydantic import ValidationError

from config import AppConfig, load_config
from models import IncidentReport
from registry import registry
import tools  # noqa: F401：导入时触发三个 @registry.register 装饰器


ROOT = Path(__file__).resolve().parent
SYSTEM_PROMPT = """你是 IncidentPilot，一个代码故障分析 Agent。
你的任务是根据用户给出的报错，在当前项目中搜索和读取代码，找到根因。
先用工具收集证据，不要猜测；不要声称看过没有读取的文件。
最终只能输出 JSON，字段必须是 summary、root_cause、evidence、suggested_fixes、confidence。
evidence 中每项必须包含 file、line、description；confidence 只能是 low、medium、high。
如果证据不足，不要编造文件或行号，应降低 confidence 并明确说明不能确定。
你只能调查和提出建议，不能修改文件。"""


def create_client() -> tuple[OpenAI, AppConfig]:
    config = load_config(ROOT)
    client = OpenAI(api_key=config.api_key, base_url=config.base_url)
    return client, config


def _response_format(config: AppConfig):
    """根据 env 选择服务商实际支持的最终输出格式。"""
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


def run_agent(user_input: str, max_steps: int = 8) -> IncidentReport:
    client, config = create_client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    for step in range(1, max_steps + 1):
        print(f"\n--- Agent 第 {step} 步 ---")
        request = {
            "model": config.model,
            "messages": messages,
            "tools": registry.schemas(strict=config.strict_tools),
            "tool_choice": "auto",
        }
        response_format = _response_format(config)
        if response_format is not None:
            request["response_format"] = response_format
        response = client.chat.completions.create(**request)
        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            if not message.content:
                messages.append({"role": "user", "content": "你没有返回内容。请只返回完整 JSON 报告。"})
                continue
            try:
                return IncidentReport.model_validate_json(message.content)
            except ValidationError as exc:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "上一个最终报告不符合要求。请根据已有证据重新输出且只输出 JSON。"
                            f"校验错误：{exc.error_count()} 处。"
                        ),
                    }
                )
                continue

        for tool_call in message.tool_calls:
            name = tool_call.function.name
            arguments = tool_call.function.arguments
            print(f"调用工具: {name}({arguments})")
            result = registry.execute(name, arguments)
            print(f"工具结果: {result[:500]}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )

    return IncidentReport(
        summary="调查达到最大步数，尚未完成。",
        root_cause="现有证据不足，无法确定根因。",
        evidence=[],
        suggested_fixes=["提供更完整的 traceback，或提高允许的调查步数。"],
        confidence="low",
    )
