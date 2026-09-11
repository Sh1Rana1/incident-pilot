# Demo App 使用说明

这是 IncidentPilot 的安全故障评测夹具，不是生产应用。代码中故意保留三个 Bug；请不要直接修复，否则对应评测将失效。

在项目根目录运行：

```powershell
.venv\Scripts\python.exe -m demo_app.run_case missing_user_id
.venv\Scripts\python.exe -m demo_app.run_case schema_mismatch
.venv\Scripts\python.exe -m demo_app.run_case connection_leak
```

三个命令都应该以非零状态结束并打印 traceback：

| 案例 | 预期异常 | 主要能力 |
|---|---|---|
| `missing_user_id` | `KeyError: 'user_id'` | 代码 + API 文档 |
| `schema_mismatch` | `no column named user_id` | 代码 + 数据库迁移文档 |
| `connection_leak` | `connection pool exhausted` | 代码 + Runbook/历史事故 |

配套材料：

- `docs/`：Agent 可以通过 RAG 检索的架构、API、数据库、Runbook 和事故复盘；
- `logs/`：可以直接粘贴给 Agent 的简化错误日志；
- `evals/`：根因关键词、证据文件和相关文档等标准答案。

测试命令：

```powershell
.venv\Scripts\python.exe -m unittest test_demo_app -v
```

这些测试通过表示 Bug 仍然能够稳定复现，而不是表示业务代码没有 Bug。
