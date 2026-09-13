# Demo App 使用说明

这是 IncidentPilot 的安全故障评测夹具，不是生产应用。代码中故意保留多个 Bug；请不要直接修复，否则对应评测将失效。

在项目根目录运行：

```powershell
.venv\Scripts\python.exe -m demo_app.run_case missing_user_id
.venv\Scripts\python.exe -m demo_app.run_case schema_mismatch
.venv\Scripts\python.exe -m demo_app.run_case connection_leak
.venv\Scripts\python.exe -m demo_app.run_case documentation_required
```

也支持直接运行脚本：

```powershell
.venv\Scripts\python.exe demo_app\run_case.py missing_user_id
```

`-m demo_app.run_case` 仍是推荐方式，因为它明确告诉 Python 按包加载模块。直接运行方式会由启动脚本自动把项目根目录加入模块搜索路径，因此不会再出现 `No module named 'demo_app'`。

四个命令都应该以非零状态结束并打印 traceback：

| 案例 | 预期异常 | 主要能力 |
|---|---|---|
| `missing_user_id` | `KeyError: 'user_id'` | 代码 + API 文档 |
| `schema_mismatch` | `no column named user_id` | 代码 + 数据库迁移文档 |
| `connection_leak` | `connection pool exhausted` | 代码 + Runbook/历史事故 |
| `documentation_required` | `timeout_policy_violation` | 供应商契约文档 |

配套材料：

- `docs/`：Agent 可以通过 RAG 检索的架构、API、数据库、Runbook 和事故复盘；
- `logs/`：可以直接粘贴给 Agent 的简化错误日志；
- `evals/`：根因关键词、证据文件和相关文档等标准答案。
- `fixtures/`：用于稳定复现外部系统行为，Agent 不可读取。

评测还提供三个专项问题：`git_regression` 复用连接泄漏代码测量 Git 历史贡献，`misleading_documentation` 测量过时文档是否干扰诊断，这两个不能单独执行；`runtime_required` 复用 `documentation_required`，但额外要求 Agent 真正运行预登记案例，并在最终报告中引用系统生成的 Runtime ID。

V9 会维护候选假设，新证据必须先归入假设才能继续调查；总结阶段保全全部真实证据候选，并把最终证据绑定到实际工具 Observation。Agent 使用的 Runtime 工具只能选择上面四个案例，不能传入任意命令。交互执行必须先在 `api.env` 设置 `ENABLE_RUNTIME_TOOLS=true`，随后每次运行仍要人工批准；Evaluation 则必须显式使用 `--profile full_runtime --allow-runtime`。

测试命令：

```powershell
.venv\Scripts\python.exe -m unittest test_demo_app -v
```

这些测试通过表示 Bug 仍然能够稳定复现，而不是表示业务代码没有 Bug。
