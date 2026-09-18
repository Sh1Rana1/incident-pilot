# Notification SDK 客户端迁移

Notification SDK v3 的发送接口为
`send(*, recipient: str, content: str) -> str`。v2 使用的 `message` 关键字已被
`content` 替代，不再接受旧名称。

应用适配层可以继续对业务代码暴露 `message` 概念，但调用 SDK v3 时必须把该值映射到
`content`；成功调用返回通知 ID。
