# Demo App 架构

## 用户创建请求链路

`POST /users` 的调用链是 `app/api.py:post_users` → `app/service.py:create_user` → `app/repository.py:insert_user` → SQLite。

API 层负责校验外部输入并返回 HTTP 400；Service 层只接收已经通过校验的业务数据；Repository 层必须使用当前数据库 Schema 中存在的字段。

## 后台任务链路

`app/worker.py:process_job` 从 `ConnectionPool` 获取连接。无论任务成功还是抛出异常，都必须释放连接。推荐用 `try/finally` 保证清理。

## 故障调查顺序

先根据 traceback 读取直接报错文件，再搜索调用方。涉及字段或层级职责时查询 API 与架构文档；涉及近期回归时检查 Git diff 和 log。
