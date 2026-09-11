# INC-003：连接池耗尽

## 现象

连续出现无效任务后，新任务报错 `connection pool exhausted`。

## 根因

Worker 获取连接后，在无效 payload 的异常路径直接抛出错误，没有释放连接。

## 正确修复

使用 `try/finally` 或上下文管理器，确保所有执行路径都释放连接。不要把扩大连接池作为根本修复。
