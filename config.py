"""只通过 api.env 切换模型供应商和兼容能力。"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


OutputMode = Literal["json_schema", "json_object", "text"]


@dataclass(frozen=True)
class AppConfig:
    api_key: str
    base_url: str
    model: str
    output_mode: OutputMode
    strict_tools: bool
    max_model_calls: int = 10
    max_tool_calls: int = 20
    max_tools_per_step: int = 3
    hitl_model_threshold: int = 5
    hitl_tool_threshold: int = 10
    runtime_tools_enabled: bool = False
    max_runtime_calls: int = 1
    runtime_timeout_seconds: int = 5


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise RuntimeError(f"{name} 必须是 true 或 false。")


def resolve_capabilities(
    base_url: str,
    output_setting: str = "auto",
    strict_setting: str = "auto",
) -> tuple[OutputMode, bool]:
    """自动识别已知服务；未知兼容服务使用保守配置。"""
    url = base_url.lower().rstrip("/")
    is_openai = "api.openai.com" in url
    is_deepseek = "api.deepseek.com" in url

    if output_setting.lower() == "auto":
        output_mode: OutputMode = "json_schema" if is_openai else "json_object"
    else:
        requested = output_setting.lower()
        if requested not in {"json_schema", "json_object", "text"}:
            raise RuntimeError(
                "OUTPUT_MODE 必须是 auto、json_schema、json_object 或 text。"
            )
        output_mode = requested  # type: ignore[assignment]

    if strict_setting.lower() == "auto":
        strict_tools = is_openai or (is_deepseek and url.endswith("/beta"))
    else:
        strict_tools = _parse_bool(strict_setting, "STRICT_TOOLS")
    return output_mode, strict_tools


def load_config(root: Path) -> AppConfig:
    load_dotenv(root / "api.env", override=True)
    api_key = os.getenv("API_KEY", "").strip()
    base_url = os.getenv("BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv("MODEL", "").strip()
    missing = [name for name, value in {"API_KEY": api_key, "MODEL": model}.items() if not value]
    if missing:
        raise RuntimeError(f"api.env 缺少配置: {', '.join(missing)}。请参考 api.env.example。")

    output_mode, strict_tools = resolve_capabilities(
        base_url,
        os.getenv("OUTPUT_MODE", "auto"),
        os.getenv("STRICT_TOOLS", "auto"),
    )
    def positive_int(name: str, default: int) -> int:
        raw = os.getenv(name, str(default)).strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} 必须是正整数。") from exc
        if value < 1:
            raise RuntimeError(f"{name} 必须是正整数。")
        return value

    return AppConfig(
        api_key,
        base_url,
        model,
        output_mode,
        strict_tools,
        max_model_calls=positive_int("MAX_MODEL_CALLS", 10),
        max_tool_calls=positive_int("MAX_TOOL_CALLS", 20),
        max_tools_per_step=positive_int("MAX_TOOLS_PER_STEP", 3),
        hitl_model_threshold=positive_int("HITL_MODEL_CALL_THRESHOLD", 5),
        hitl_tool_threshold=positive_int("HITL_TOOL_CALL_THRESHOLD", 10),
        runtime_tools_enabled=_parse_bool(
            os.getenv("ENABLE_RUNTIME_TOOLS", "false"),
            "ENABLE_RUNTIME_TOOLS",
        ),
        max_runtime_calls=positive_int("MAX_RUNTIME_CALLS", 1),
        runtime_timeout_seconds=positive_int("RUNTIME_TIMEOUT_SECONDS", 5),
    )
