# Demo App 数据库

## users 表当前 Schema

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    external_id TEXT UNIQUE,
    email TEXT NOT NULL
);
```

## 字段迁移 MIG-2026-001

2026-08-10，`users.user_id` 被重命名为 `users.external_id`。迁移后所有 Repository 查询和写入必须使用 `external_id`。

为了保持外部 API 兼容，HTTP 请求字段仍叫 `user_id`；Service 或 Repository 负责将请求字段映射到数据库的 `external_id`。不得继续执行包含 `users.user_id` 的 SQL。
