# INC-002：数据库字段迁移不一致

## 现象

创建用户时 SQLite 报错：`table users has no column named user_id`。

## 根因

数据库迁移已把 `user_id` 改为 `external_id`，Repository 的 INSERT SQL 仍使用旧字段。

## 正确修复

将 Repository SQL 的目标字段改为 `external_id`，并增加覆盖真实迁移后 Schema 的集成测试。
