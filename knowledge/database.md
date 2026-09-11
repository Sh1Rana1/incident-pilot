# 数据与持久化

## 当前状态

IncidentPilot V4 当前没有业务数据库。Agent 的报告只返回给命令行，没有写入数据库。

LangGraph 使用 `InMemorySaver` 保存执行步骤的 checkpoint。它只在当前 Python 进程内有效，程序退出后数据会丢失。

## 后续持久化约定

如果需要跨进程恢复调查，应优先使用 SQLite checkpointer 进行单机开发，再使用 PostgreSQL checkpointer 支持生产并发。每次调查必须使用独立 `thread_id`，不能让不同用户共享状态。

不得把 API 密钥、完整环境变量或未经脱敏的用户数据写入 checkpoint。

## 常见问题

如果重启程序后无法恢复旧调查，这是 `InMemorySaver` 的预期行为，不是数据库故障。
