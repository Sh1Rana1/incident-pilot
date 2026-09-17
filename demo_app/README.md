# Demo App 使用说明

这是 IncidentPilot 的安全故障评测夹具，不是生产应用。代码中故意保留多个 Bug；请不要直接修复，否则对应评测将失效。

在项目根目录运行：

```powershell
.venv\Scripts\python.exe -m demo_app.run_case missing_user_id
.venv\Scripts\python.exe -m demo_app.run_case schema_mismatch
.venv\Scripts\python.exe -m demo_app.run_case connection_leak
.venv\Scripts\python.exe -m demo_app.run_case documentation_required
.venv\Scripts\python.exe -m demo_app.run_case async_missing_await
.venv\Scripts\python.exe -m demo_app.run_case retry_non_idempotent
.venv\Scripts\python.exe -m demo_app.run_case timezone_mismatch
.venv\Scripts\python.exe -m demo_app.run_case cache_key_version
.venv\Scripts\python.exe -m demo_app.run_case pagination_off_by_one
.venv\Scripts\python.exe -m demo_app.run_case config_env_rename
.venv\Scripts\python.exe -m demo_app.run_case transaction_rollback
.venv\Scripts\python.exe -m demo_app.run_case dependency_contract_change
```

也支持直接运行脚本：

```powershell
.venv\Scripts\python.exe demo_app\run_case.py missing_user_id
```

`-m demo_app.run_case` 仍是推荐方式，因为它明确告诉 Python 按包加载模块。直接运行方式会由启动脚本自动把项目根目录加入模块搜索路径，因此不会再出现 `No module named 'demo_app'`。

十二个命令都应该以非零状态结束并打印 traceback：

| 案例 | 预期异常 | 主要能力 |
|---|---|---|
| `missing_user_id` | `KeyError: 'user_id'` | 代码 + API 文档 |
| `schema_mismatch` | `no column named user_id` | 代码 + 数据库迁移文档 |
| `connection_leak` | `connection pool exhausted` | 代码 + Runbook |
| `documentation_required` | `timeout_policy_violation` | 供应商契约文档 |
| `async_missing_await` | `coroutine object is not subscriptable` | 异步边界 + Runtime 契约 |
| `retry_non_idempotent` | `duplicate charge` | 非幂等重试 + 可靠性契约 |
| `timezone_mismatch` | `offset-naive and offset-aware` | 时间标准化 |
| `cache_key_version` | `profile:v1` KeyError | 跨版本数据契约 |
| `pagination_off_by_one` | `expected 6, got 4` | 边界条件 |
| `config_env_rename` | `loaded 5000, expected 1200` | 配置迁移 |
| `transaction_rollback` | `within a transaction` | 异常后的事务恢复 |
| `dependency_contract_change` | `unexpected keyword argument 'to'` | SDK 升级契约 |

配套材料：

- `docs/`：Agent 可以通过 RAG 检索的架构、API、数据库、Runbook 和公开契约；
- `logs/`：可以直接粘贴给 Agent 的简化错误日志；
- `evals/`：根因关键词、证据文件和相关文档等标准答案。
- `fixtures/`：用于稳定复现外部系统行为，Agent 不可读取。

评测共有 15 项：5 项 development 用于开发调试，10 项 hidden 用于最终对照。`git_regression` 复用连接泄漏代码测量 Git 历史贡献，`misleading_documentation` 测量过时文档是否干扰诊断，这两个不能单独执行；`runtime_required` 复用 `documentation_required`，但额外要求 Agent 真正运行预登记案例，并在最终报告中引用系统生成的 Runtime ID。普通 Profile 会在调用模型前跳过这个 Runtime 专项案例；显式选择时必须使用 `full_runtime --allow-runtime`。完整标准答案只存在于 Agent 不可读取的 `evals/`，所有测试源码与 `checks/` 实现同样不会暴露给 Agent 文件工具。

Agent 会维护候选假设，新证据必须先归入假设才能继续调查；总结阶段保全全部真实证据候选，并把最终证据绑定到实际工具 Observation。Runtime 工具只能选择预登记案例，不能传入任意命令。交互执行必须先在 `api.env` 设置 `ENABLE_RUNTIME_TOOLS=true`，随后每次运行仍要人工批准；Evaluation 则必须显式使用 `--profile full_runtime --allow-runtime`。

测试命令：

```powershell
.venv\Scripts\python.exe -m unittest test_demo_app -v
```

这些测试通过表示 Bug 仍然能够稳定复现，而不是表示业务代码没有 Bug。
