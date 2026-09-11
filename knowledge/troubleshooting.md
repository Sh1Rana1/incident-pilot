# 排障手册

## response_format 不可用

现象：服务返回 HTTP 400，并提示 `This response_format type is unavailable now`。

原因：模型服务不支持请求中的 `json_schema` 输出模式。例如 DeepSeek Chat Completions 使用 `json_object`。

处理：保持 `OUTPUT_MODE=auto`，或手动设置 `OUTPUT_MODE=json_object`。返回内容仍会经过本地 Pydantic 校验。

## 找不到 langgraph

现象：出现 `ModuleNotFoundError: No module named 'langgraph'`。

处理：激活项目 `.venv`，然后运行 `python -m pip install -r requirements.txt`。V3 及之后版本要求 Python 3.10+。

## 调查重启后丢失

原因：当前 checkpoint 使用 `InMemorySaver`，不会写入永久数据库。需要跨进程恢复时，应迁移到 SQLite 或 PostgreSQL checkpointer。

## Agent 搜索不到信息

先提供完整 traceback。模型可以用 `list_files` 查看结构、用 `search_code` 搜索代码、用 `retrieve_docs` 查询项目规范，也可以通过只读 Git 工具检查最近变更。
