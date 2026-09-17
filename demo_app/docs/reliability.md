# Reliability Contracts

## Payment retry

支付网关超时不代表扣款失败：响应可能在扣款完成后丢失。调用方只能使用稳定的 idempotency key 重试，或者先按订单号查询交易状态。对结果未知的非幂等写操作进行无条件重试，可能产生重复副作用。

## Database transaction recovery

批量导入在显式事务中运行。任意记录校验失败后，必须先执行 `rollback()`，再开始下一批事务；仅捕获异常不会清除 SQLite 连接上的活动事务。
