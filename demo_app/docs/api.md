# Demo App API

## POST /users

创建用户。请求 JSON 必须包含：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `user_id` | string | 是 | 外部用户唯一标识 |
| `email` | string | 是 | 用户邮箱 |

缺少必填字段时，API 层必须返回 HTTP 400，并且不能调用 Service 或 Repository。成功时返回 HTTP 201。

## 错误处理约定

外部输入错误属于客户端错误，不应以未处理的 `KeyError` 和 HTTP 500 暴露。API 层应把字段校验错误转换为稳定的错误响应。
