# Python Runtime Contracts

## Async loader

账单模块的 `load_invoice()` 是异步接口，调用后得到 awaitable。业务代码必须先在异步上下文中等待结果，再访问账单字段。同步入口需要使用明确的异步边界，不能把 coroutine 当作已经解析的字典。

## Timestamp policy

任务服务交换的时间戳统一使用 UTC ISO-8601，并保留 `+00:00` 时区信息。参与排序或 SLA 比较的两个 `datetime` 必须同时为 timezone-aware；禁止把带时区时间与本地 naive 时间直接比较。
