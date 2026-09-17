# Data Access Contracts

## Profile cache namespace

用户资料缓存已经迁移到 `profile:v2:{user_id}` 命名空间。迁移期间写入方和读取方必须共享同一个版本常量；旧的 `profile:v1` Key 不会自动回退到新命名空间。

## Pagination

记录服务的页码从 1 开始，`total_pages` 表示包含最后一页在内的总页数。例如 `total_pages=3` 时，客户端必须请求第 1、2、3 页。聚合完成后应核对实际记录数与分页元数据。
