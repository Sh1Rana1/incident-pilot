"""IncidentPilot V3 的公开入口；控制流已经迁移到 LangGraph。"""

from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from openai import OpenAI

from config import AppConfig, load_config
from graph import SYSTEM_PROMPT, build_agent_graph
from models import IncidentReport


ROOT = Path(__file__).resolve().parent
CHECKPOINTER = InMemorySaver()


def create_client() -> tuple[OpenAI, AppConfig]:
    config = load_config(ROOT)
    return OpenAI(api_key=config.api_key, base_url=config.base_url), config


def run_agent(
    user_input: str,
    max_steps: int = 8,
    thread_id: str | None = None,
) -> IncidentReport:
    """运行状态图；每个新问题默认使用独立 checkpoint 线程。"""
    client, config = create_client()
    app = build_agent_graph(client, config, CHECKPOINTER)
    initial_state = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        "step_count": 0,
        "tool_call_count": 0,
        "max_steps": max_steps,
        "report": None,
        "validation_error": None,
        "stop_reason": None,
    }
    runtime_config = {
        "configurable": {"thread_id": thread_id or str(uuid4())},
        "recursion_limit": max_steps * 3 + 5,
    }
    final_state = app.invoke(initial_state, config=runtime_config)
    return IncidentReport.model_validate(final_state["report"])
