# 模型 API 与配置约定

## 配置文件

模型配置位于根目录 `api.env`，包含 `API_KEY`、`BASE_URL` 和 `MODEL`。该文件是敏感文件，不能提交到 Git，也不能被 Agent 的文件工具读取。

## 输出兼容模式

OpenAI 官方地址默认使用 `json_schema`；DeepSeek 默认使用 `json_object`，再由本地 Pydantic 验证。其他 OpenAI 兼容服务默认使用较保守的 `json_object` 和非严格工具模式。

可通过 `OUTPUT_MODE` 和 `STRICT_TOOLS` 在配置文件中覆盖自动判断。

## 工具调用协议

模型产生 `tool_calls` 后，程序必须为每次调用返回带有相同 `tool_call_id` 的工具消息。工具参数始终被视为不可信输入，执行前必须经过 Pydantic 校验。
