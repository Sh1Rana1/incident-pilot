# Demo App Runbook

## KeyError 排查

查看 traceback 中被索引的字典键，再检查 API 层是否验证必填字段。不要只把方括号访问改成 `.get()`，否则可能把明确错误变成更晚出现的空值错误。

## no column named user_id

先对照数据库 Schema 与迁移记录，再搜索 Repository 中的 SQL。重点检查迁移是否只修改数据库而遗漏应用代码。

## connection pool exhausted

检查每次 `acquire()` 是否在所有成功和异常路径执行 `release()`。优先寻找缺少 `finally`、上下文管理器或异常处理的代码。扩大连接池只能暂时延迟故障，不能修复连接泄漏。
