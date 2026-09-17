# Client Migration Notes

## Timeout environment variable

通知服务在 2026-09 配置迁移后使用 `SERVICE_TIMEOUT_MS`。旧名称 `REQUEST_TIMEOUT_MS` 已停止注入；应用不得在新变量缺失时悄悄退回旧配置默认值。当前演示环境期望 1200ms。

## Notify SDK v3

Notify SDK v3 将 `send_message()` 的接收方关键字参数从 `to` 改为 `recipient`，`message` 保持不变。升级后继续传入 `to=` 会由 Python 参数绑定直接拒绝。
