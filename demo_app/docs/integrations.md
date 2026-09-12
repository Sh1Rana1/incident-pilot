# Webhook 供应商契约

## Acme Notify v2

生产环境已迁移到 Acme Notify v2。请求字段 `timeout_seconds` 的硬上限是 **10 秒**；
超过上限时供应商返回 `HTTP 422: timeout_policy_violation`，不会发送 webhook。

应用侧应把 webhook 超时配置设为 10 秒或更低。旧版 v1 曾允许 30 秒，迁移到 v2 后该值已失效。

排障时不要把 422 当成网络超时：它代表请求违反供应商契约，应先核对应用配置和当前供应商版本。
