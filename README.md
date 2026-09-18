# IncidentPilot V14.7 · Deterministic Benchmark Audit

V14.1 增加了异步资料查询与订单支付重试两个离线故障案例，V14.2 冻结五个 development 案例的 V13 基线，V14.3 完成五项可泛化调查优化和正式对照。V14.4–V14.6 保持 Agent 控制流不变，分三批加入时区、缓存 Key、分页边界、环境变量改名、事务回滚和 SDK 契约变化案例，达到十二个可执行场景、十五个 Evaluation 案例、二十二个 Harness Check。V14.7 新增完全本地的确定性审计，把划分、资产、复现、Harness 映射、RAG 可发现性、答案隔离、评分关键词来源和冻结报告哈希纳入同一份机器可读报告；它不创建模型客户端，也不调用 DeepSeek。

审计发现并修复了五处“评分术语在允许取证材料中缺少字面支撑”的数据质量问题：异步契约补充 `coroutine/await`，分页契约补充 `1-based`，支付契约补充“超时”，事务契约补充 `rollback`。没有改动 `graph.py`、评分器、冻结的 V13/V14.3 结果或任何 Case ID 专用调查规则。相同五案例、Profile、预算和模型下的历史单次对照继续保持冻结；新 hidden 案例不回写历史结果，也不能把单次小样本外推为生产稳定性。

正式审计在干净提交 `af1be13` 上完成：166/166 项检查通过，失败 0 项；十五个 Evaluation 按 development 5、hidden 7、challenge 2、runtime 1 唯一分组，十二个场景完成模块/脚本共 24 次预期故障复现，22/22 个 Harness Check 的当前行为符合用途，所有相关文档均进入本地索引并能从案例问题的前 8 条结果中发现，评分关键词缺少来源 0 项、RAG 漏检 0 项、受保护资产泄漏 0 项。V13 的两份原始基线和 V14.3 的一份原始报告均存在且 SHA-256 与冻结汇总一致；审计专项 70 项、全量 198 项离线测试及 `doctor` 均通过。完整报告为 `demo_app/evals/results/v14.7-deterministic-audit.json`，文件 SHA-256 为 `ee970f210ab7c802eafec2602266e382adf82881ac6d6bc124a510f16e4dd890`。

验证基点为 V13 `8c804fb`：修改前 155 项离线测试及 `main.py doctor` 通过。新增案例各包含故障代码、复现入口、简化日志、业务契约、复现/回归 Harness 和 Evaluation 标准。回归测试会在临时副本应用参考修复，验证入口与契约检查均通过，正式故障代码保留原样。

本阶段补上所有 `test_*.py`、`checks`、Harness/Runtime 实现、Fixture 和 Eval 的文件工具隔离。三个直接写出旧案例根因和修复的事故文档已移除，业务代码中的答案式注释也已清理；Evaluation 改为引用正常的 API、数据库和 Runbook 契约。`_benchmark_manifest.json` 冻结开发、hidden、challenge 和 Runtime 集合，默认实验只选择 development。

2026-09-18 首次 `missing_user_id + full` 烟雾运行虽然得到 1/1，但搜索结果暴露了 `test_graph.py`，最终报告还把测试中的标准结论列为 Evidence，因此该报告已移入 `.incident_reports/quarantine/v13/` 并标记 invalid，不能作为基线或简历数据。之后完成隔离修复并重新取得了来源审计通过的正式基线。

隔离修复提交 `3c1b4b8` 上的第二次单案例运行来源审计通过，可作为 V13 development 基线样本。结果为 0/1：根因关键词 33%、代码文件覆盖 50%、文档覆盖 0%，引用、Evidence 落地和 Claim 覆盖均为 100%，Provenance 违规 0；模型调用 10 次、工具调用 13 次、Token 61,085、耗时 60.58 秒、格式修复 1 次、fallback 0 次、Observation 利用率 83%。Agent 找到了 Service 的 `payload["user_id"]` 直接报错点，但没有读取 API 入口或业务契约，8 步的后半段连续更新假设，因此遗漏“API 缺少校验”这一系统根因。该结果是单案例单次样本，不能外推为总体通过率。

五个 development 案例的 V13 基线现已完成，每例一次，来源审计全部通过。总体通过 1/5（20%），平均根因覆盖 40%、代码文件覆盖 50%、文档覆盖 20%、引用有效率 60%、Observation 利用率 61%；平均每例 9.8 次模型调用、13.6 次工具调用和 57,337 Token，总 Token 286,683、总耗时 262.84 秒。格式修复 4/5，fallback 2/5，Provenance 违规和重复工具调用均为 0。只有 `retry_non_idempotent` 通过；详细逐例数据保存在 `demo_app/evals/results/v13-v14.1-development.json`。这是固定模型与配置下的单次小样本，后续只能与相同五案例、Profile 和预算的 V14 结果比较。

V14.3 第一项优化完成后，只运行了一次预先指定的 `schema_mismatch + full` 付费验收：由 V13 的失败变为 1/1 通过，根因与代码文件覆盖均为 100%，引用、Evidence 落地和 Claim 覆盖均为 100%，Provenance 违规 0；模型调用由 10 降为 5，工具调用由 12 降为 8，Token 由 56,844 降为 22,005，耗时由 50.15 秒降为 22.28 秒，格式修复由 1 次降为 0，fallback 保持 0。Agent 在第 4 个调查步骤形成 confirmed 假设并提前总结，没有重现 V13 第 5–8 步的假设更新空转。Observation 利用率由 83% 降为 60%，文档覆盖仍为 0%，说明这次修复解决的是控制流浪费，不代表所有质量指标都提升。该结果是单案例单次验收，报告为 `.incident_reports/eval-20260918-190005.json`，不能替代后续五案例正式 V14 对照。

第二项优化在干净提交 `4c2200e` 上只运行了一次 `missing_user_id + full`：DeepSeek 严格 Schema 正常接受 nullable 行号，实际执行 `run_case.py:1–30`、`run_case.py:31–60` 和 `service.py:1–30` 三次定向读取，没有出现 400 或整文件读取。机器评分由 V13 的失败变为 1/1 通过，模型调用 10→5、工具调用 13→8、Token 61,085→23,705、耗时 60.58→20.76 秒，格式修复 1→0，fallback 维持 0。但人工审计不把它视为完整系统根因通过：报告没有读取 `api.py` 或 `api.md`，代码文件覆盖只有 50%、文档覆盖 0%，并明确承认 API 层是否校验尚未验证；Observation 利用率也由 83% 降到 50%。这说明定向读取和严格 Schema 已验收，但当前确定性评分阈值会接受只覆盖一半必需代码文件、未覆盖文档的报告，后续仍需上游契约追踪与正式对照。原始报告为 `.incident_reports/eval-20260918-192237.json`，SHA-256 为 `c5cd3d966dae102ae6fe05d1915531ca8ce00a1f5915a652de8491ab2960a2ff`。

第三项优化针对“工具已经读到关键行，但下一轮模型只看到摘要开头”的信息损失。成功的定向 `read_file` 不再截取原始 JSON 前 1,000 字符，而是转为紧凑的 `行号: 内容` 格式，并在最多 4,000 字符内为窗口中的每一行分配内容预算；压缩上下文对这类 Observation 同样保留最多 4,000 字符。普通工具仍保持 Observation 1,000 字符、模型上下文 700 字符的旧上限，完整结果哈希、精确来源和 Checkpoint 中的工具消息不变。

该项在干净提交 `5a88208` 上只运行了一次 `missing_user_id + full`。定向读取 `run_case.py:20–49` 的压缩摘要完整保留到第 49 行，包含第 35–36 行缺少 `user_id` 的调用；Agent 随后继续读取 `api.py`、`service.py` 和 `repository.py`。最终报告明确给出“入口构造非法 payload → API 不校验直接透传 → Service 用 `payload["user_id"]` 抛出 `KeyError`”的完整链路，机器评分 1/1，根因、代码文件、引用、Evidence 落地和 Claim 覆盖均为 100%，Provenance 违规 0，形成两个 confirmed 假设并提前结束。与 V13 基线相比，模型调用 10→8、Token 61,085→44,612、耗时 60.58→47.67 秒、格式修复 1→0，工具调用均为 13；Observation 利用率 83%→75%。与第二项的单次验收相比，诊断覆盖更完整，但模型调用 5→8、工具调用 8→13、Token 23,705→44,612，不能把随机单样本解释为成本稳定改善。文档覆盖仍为 0%，并有两条成功 Observation 未用于报告。原始报告为 `.incident_reports/eval-20260918-195735.json`，SHA-256 为 `f1567eaf6cbf2e1a9f8750ecb29a111abc7437985c0d3f1f70a62b2b3f2175dd`。

第四项优化把重复读取判断从“工具名和 JSON 参数完全相同”扩展到成功 `read_file` Observation 的真实文件行区间。新定向窗口如果已由一个或多个成功窗口的并集完整覆盖，执行层返回 `duplicate_read_range` 和可复用的 Observation ID，不再访问文件；只要还包含至少一行未覆盖内容就继续执行。失败、越界、被预算拦截或已标为重复的 Observation 不会建立覆盖范围。

该项在干净提交 `2cc5f0a` 上只运行了一次 `missing_user_id + full`，机器评分继续为 1/1；根因、代码文件、引用、Evidence 落地和 Claim 覆盖均为 100%，Provenance 违规、格式修复和 fallback 均为 0。报告仍完整说明“缺少 `user_id` 的案例输入 → API 原样透传 → Service 下标访问触发 `KeyError`”，但置信度为 medium、没有 confirmed 假设或早停，文档覆盖仍为 0%，三条成功 Observation 未用于报告。模型调用 9 次、工具调用 16 次、Token 42,336、耗时 42.28 秒、Observation 利用率 66.67%。本次唯一重复是精确相同的 `search_code("user_id")`，没有提出被旧范围完整覆盖的新 `read_file` 窗口，因此只能作为无回归验收，不能声称真实模型运行触发了新分支；区间去重行为由离线执行层回归确定性验证。模型还产生了三次超过 30 行的失败读取和一次 Profile 不允许的 `list_checks`，说明工具规划仍有优化空间。原始报告为 `.incident_reports/eval-20260918-201809.json`，SHA-256 为 `a3050fb4c5bf0e672990b1b15de61b6849822522ed5fecd2c4fb7f0980b477c0`。

第五项优化新增独立的 `classify_final_evidence` 节点：如果最后一个调查步骤产生了尚未归类的成功 Observation，且总模型预算仍能同时容纳“归类、总结、格式修复”三次请求，系统会先执行一次只暴露 `update_hypotheses` 的受限归类。该请求计入模型调用和 Token，但不增加调查 `step_count`；归类完成后立即总结，不再开放外部工具。即使兼容服务返回未声明的外部工具，执行层也会以 `final_classification_only` 拒绝。系统提示同时把异常行定义为 failure site，要求继续核对至少一个上游调用方和相关接口或业务契约；`KeyError`、缺字段和非法输入必须优先检查入口校验，不能把下游 `.get()` 当作完整根因修复。

该项在干净提交 `f43f30d` 上只运行了一次 `missing_user_id + full`，机器评分 1/1；根因、必需代码文件、文档、引用、Evidence 落地和 Claim 覆盖均为 100%，Provenance 违规、重复调用和 fallback 均为 0。Agent 读取了缺字段调用、`api.py`、`service.py`、`repository.py` 与 `api.md` 契约，最终明确区分“Service 下标访问是 failure site”和“API 未按契约校验并阻断非法 payload 是系统根因”，3 个假设均 confirmed 并提前结束。模型调用 9 次、工具调用 13 次、Token 51,686、耗时 57.30 秒、Observation 利用率 77.78%，发生 1 次格式修复。`final_classification_count=0`：最后证据已在第 7 个调查步骤正常归类并触发早停，因此这次真实运行验证了上游根因追踪和新指标兼容性，但没有触发预算末尾的受限归类分支；该分支仍由离线回归确定性验证。原始报告为 `.incident_reports/eval-20260918-212806.json`，SHA-256 为 `f6a6ecc35a6e0880dbc31826f2c29f6081ac225b1265b2cfc1b8ba80d1eaa23b`。

正式 development 对照在干净提交 `234a2a4` 上按五个冻结案例、`full` Profile、每例一次完成。V14.3 通过 3/5（60%），V13 为 1/5（20%），通过率提高 40 个百分点；平均根因覆盖 40%→93.33%、代码覆盖 50%→100%、文档覆盖 20%→80%、引用/Evidence/Claim 覆盖均由 60%→100%，Observation 利用率 61.07%→70.62%。平均模型调用 9.8→8.6（下降 12.24%），平均 Token 57,336.6→52,684.2（下降 8.11%），格式修复 4→2、fallback 2→1；但平均工具调用 13.6→14.0（增加 2.94%），总耗时 262.84→321.25 秒（增加 22.22%），不能声称所有效率指标都改善。受限最后归类在 `connection_leak` 与 `retry_non_idempotent` 中各真实触发一次，前者生成合法报告，后者根因正确但最终 Evidence 越界且格式修复失败，验证器将其拒绝为 `invalid_synthesis`。

两个失败均保留原判：`async_missing_await` 已正确说明漏写 `await` 和 coroutine object，但没有命中确定性标准中的中文关键词“协程”；`retry_non_idempotent` 的两个 confirmed 假设正确，但最终报告扩写了 Observation 未覆盖的来源并留下未被 Claim 使用的 Evidence。没有为提高通过率修改关键词、来源白名单或报告验证器。逐例审计与精确差值保存在 `demo_app/evals/results/v14.3-development.json`；被 Git 忽略的原始报告为 `.incident_reports/baselines/v14.3-development/v14.1-development-20260918-215356.json`，SHA-256 为 `3df3d595413c8646d6dfb1493c80e4412076b6c3806e842262708df456c3d64e`。

正式对照后针对 `retry_non_idempotent` 暴露的通用来源错配完成加固。总结与格式修复不再收到“Observation 内嵌 sources 数组”，而是收到逐条展开的精确 Evidence 来源白名单；每项直接包含 `observation_id/source_type/file/line_start/line_end/commit_hash/runtime_id`。成功但没有来源的 Observation（例如零命中的搜索）不进入白名单，只能作为推理线索；模型必须完整复制一个白名单对象，不能把一个 Observation ID 与另一个来源拼接。格式修复还明确要求整项替换或删除不合法 Evidence，并删除没有 Claim 使用的游离 Evidence。Provenance Validator 及评分标准没有放宽。

该项在干净提交 `38494ed` 上只运行了一次 `retry_non_idempotent + full`，机器评分 1/1；根因、必需代码、引用、Evidence 落地和 Claim 覆盖均为 100%，Provenance 违规 0，fallback 0。Agent 正确识别“首次支付可能已在服务端成功、客户端因超时重试、请求没有幂等键，因此发生重复扣款”，并把 `run_case.py:58` 区分为检测/失败位置。首次生成的报告只有一项未被 Claim 使用的 Evidence `E2`，唯一一次格式修复将其删除；没有再出现 Observation ID 与文件/行号错配。模型调用 9 次、工具调用 15 次，其中唯一外部调用 12 次，Token 55,142、耗时 57.12 秒、Observation 利用率 66.67%。文档覆盖为 0%，因为本次 RAG 没有返回支付契约正文；报告据实保留“契约未确认”的不确定性，Fixture 读取也被隔离规则阻止。原始报告为 `.incident_reports/eval-20260918-232704.json`，SHA-256 为 `bd3ba81c0615f299c60be8d526d29ed36ca15719c49c9cf25cbc0873e5c59cff`。这是修复后的单案例验收，不属于已冻结的五案例正式对照，也不覆盖 `demo_app/evals/results/v14.3-development.json` 中的 3/5 结果。

新增案例可离线复现：

```powershell
.\.venv\Scripts\python.exe -m demo_app.run_case async_missing_await
.\.venv\Scripts\python.exe -m demo_app.run_case retry_non_idempotent
.\.venv\Scripts\python.exe -m demo_app.run_case timezone_mismatch
.\.venv\Scripts\python.exe -m demo_app.run_case cache_key_version
.\.venv\Scripts\python.exe -m demo_app.run_case pagination_off_by_one
.\.venv\Scripts\python.exe -m demo_app.run_case config_env_rename
.\.venv\Scripts\python.exe -m demo_app.run_case transaction_rollback
.\.venv\Scripts\python.exe -m demo_app.run_case dependency_contract_change
.\.venv\Scripts\python.exe -m unittest test_demo_app -v
```

前八条在故障版本中预期非零退出。扩展案例通过 `run_check` 的预登记检查运行；兼容工具 `run_demo_case` 仍只接受 V13 的四个案例。八个扩展案例都有故意在故障版本失败的按需契约检查，其中最终批新增 `transaction_atomicity_contract` 与 `notification_sdk_v3_contract`；默认测试会验证这些失败确实被检测到，并在临时副本应用参考修复后验证复现入口与契约检查共同通过。

IncidentPilot 是一个面向 Python 项目的证据驱动故障诊断 Agent。用户提交 traceback 或问题描述后，模型通过受控工具查看代码、文档和 Git 信息，并可在人工批准后运行 Safe Test Harness，取得真实 Runtime Evidence。V13 在严格 Patch Proposal 之后增加独立审批与临时副本验证：系统先在副本中确认原故障可复现，再应用候选 diff，最后运行覆盖修改文件的契约检查和全局回归检查。正式工作区始终不被修改，验证过程也不会再调用模型。

当前版本的重点是：

- 使用 LangGraph 显式组织 Agent 控制流；
- 每次模型请求前压缩历史，只发送原始问题、当前假设和必要 Observation 摘要；
- 总结和格式修复时切换到证据保全模式，重新纳入所有带真实来源的成功 Observation；
- 每轮最多执行三个外部工具，阻止一次响应并发铺开大量低价值调查；
- 使用统一注册器管理八个只读调查工具和两个受限运行时工具；
- 使用 `harness.json` 预登记测试；模型只能调用 `list_checks()` 和 `run_check(check_id)`，不能提交命令、路径、参数或环境变量；
- 支持固定的 `demo_case`、`unittest` 和 `pytest` Runner，并返回退出码、通过/失败数量、失败测试名和异常摘要；
- 使用 `main.py new --with-patch` 生成只读提案，或用 `--verify-patch` 生成并请求隔离验证；普通调查和 Evaluation 默认不增加模型调用；
- 补丁必须绑定真实诊断 Claim、已经读取的代码 Evidence 和已登记 Harness 检查；
- 本地解析 unified diff，验证文件头、hunk 行数、当前文件上下文、改动范围和受保护路径；
- V13 只在系统创建的临时副本中应用候选补丁；补丁仍不能修改测试、Harness、Evaluation 或配置；
- 区分 `reproduction` 与 `regression`：前者要求补丁前复现故障、补丁后故障消失，后者要求补丁后继续通过；
- 根据 `covers_files` 自动加入覆盖修改文件的检查，并始终加入全局回归检查；没有覆盖检查的修改拒绝验证；
- 在任何临时写入和子进程启动前使用独立 HITL 审批，拒绝后不创建临时目录；
- 使用内部 `update_hypotheses` 控制工具维护候选根因、支持证据和反证；
- 使用结构化 `next_action` 明确下一工具、目的、支持条件和否定条件；
- 新证据产生后强制先更新假设，未归类前禁止继续调用外部工具；
- 在 confirmed 假设获得两项独立 Observation 后提前总结；
- 使用 LangGraph 原生 interrupt 和 checkpoint 实现人工暂停与恢复；
- 同时限制调查轮数、模型调用数和工具调用数；
- 记录服务商返回的输入、输出和总 Token；
- 使用本地 RAG 检索项目文档；
- 使用只读 Git 工具调查变更；
- 使用 Pydantic 验证最终报告；
- 使用确定性 Evaluation 检查根因、证据和成本；
- 使用工具级与路径级双重隔离的三种 Tool Profile 做消融实验；
- 重复运行同一道题并统计稳定性；
- 保存结构化 Tool Observation 调查轨迹；
- 使用 Claim—Evidence Ledger 将结论绑定到实际工具结果；
- 验证代码行、RAG 片段和 Git 提交的真实来源；
- 将每次 Runtime 复现绑定到系统生成的 `runtime_id`，并验证报告引用确实来自对应 Observation；
- 对运行时能力实施“配置开关 + Profile 白名单 + 单次人工批准 + 执行层预算”四层控制；
- 使用 SQLiteSaver 保存图状态，支持跨进程的 `new/list/show/resume` 调查生命周期；
- 正常运行遇到 interrupt 时当场询问并自动恢复，只有退出终端或使用 `--detach` 才需要手工 `resume`；
- 提供完全本地的 `doctor` 启动自检和已验证版本锁定文件；
- 使用持久幂等账本保护 Runtime：已完成的同一执行只返回原结果，结果不确定时拒绝自动重跑；
- 只从正常完成、中/高置信度、Claim 和 Evidence 完整的报告生成待审批 Memory；
- 只召回 `approved` Memory，并在模型上下文中明确标记“不是当前证据”；
- 使用无模型调用的本地可解释词法召回，可列出、搜索、批准、拒绝和删除记忆；
- 统计上下文压缩、Observation 利用率和确认根因后的额外调用。
- 将每次报告验证错误持久化到 Evaluation JSON，保留字段路径和具体原因。

当前版本不会执行模型生成的任意命令，不会修改正式工作区或操作生产环境。它只能运行 `harness.json` 中由项目所有者预登记并通过安全校验的检查，以及为兼容旧版本保留的四个固定 Demo Case；Runtime 默认关闭。Patch Proposal 的 `validated` 只表示格式与范围合法；只有隔离验证结果为 `verified`，才表示当次临时副本中的基线、补丁应用和补丁后检查全部满足 V13 规则。这里的“隔离”是临时工作区隔离，不是容器或操作系统安全沙箱。模型能看到工具返回的代码、文档片段和运行结果，因此使用第三方模型服务前，应确认这些内容允许发送给该服务商。

版本演进单独记录在 [CHANGELOG.md](CHANGELOG.md)。README 只描述当前 V13 的真实实现。

## 1. 快速开始

### 1.1 环境要求

- Windows PowerShell；
- Python 3.10 或更高版本；
- 一个支持 OpenAI 兼容 Chat Completions 和 Tool Calling 的模型服务；
- Git 仅在使用 Git 工具时需要。

项目依赖：

```text
openai>=1.0.0
python-dotenv>=1.0.0
pydantic>=2.0.0
langgraph>=1.0.0,<2.0.0
langgraph-checkpoint-sqlite>=3.0.0,<4.0.0
```

### 1.2 创建虚拟环境并安装依赖

在项目根目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` 保留兼容版本范围，适合日常升级；如果需要复现本次已经完整验证的稳定环境，使用：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
```

后续命令直接使用 `.venv\Scripts\python.exe`，不要求激活虚拟环境，也可以避免误用系统中的另一个 Python。

如果 PowerShell 在执行 `Activate.ps1` 时提示“在此系统上禁止运行脚本”，说明 Windows Execution Policy 阻止了激活脚本，并不表示虚拟环境损坏。推荐跳过激活，直接运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

注意路径开头是 `.\`，完整形式为 `.\.venv`，不是 `..venv`。如果确实希望激活，可以只为当前 PowerShell 窗口临时放行，再执行激活脚本：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

`-Scope Process` 只影响当前 PowerShell 进程；关闭窗口后失效，不会永久修改系统策略。

### 1.3 配置模型 API

复制 `api.env.example` 为 `api.env`，然后填写：

```env
API_KEY=你的真实密钥
BASE_URL=服务商提供的OpenAI兼容地址
MODEL=服务商提供的模型ID
OUTPUT_MODE=auto
STRICT_TOOLS=auto
MAX_MODEL_CALLS=10
MAX_TOOL_CALLS=20
MAX_TOOLS_PER_STEP=3
HITL_MODEL_CALL_THRESHOLD=5
HITL_TOOL_CALL_THRESHOLD=10
ENABLE_RUNTIME_TOOLS=false
MAX_RUNTIME_CALLS=1
RUNTIME_TIMEOUT_SECONDS=5
```

字段含义：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `API_KEY` | 是 | 模型服务密钥 |
| `BASE_URL` | 否 | OpenAI 兼容 API 地址，默认是 OpenAI 官方地址 |
| `MODEL` | 是 | 模型 ID，必须支持 Tool Calling |
| `OUTPUT_MODE` | 否 | `auto`、`json_schema`、`json_object` 或 `text` |
| `STRICT_TOOLS` | 否 | `auto`、`true` 或 `false` |
| `MAX_MODEL_CALLS` | 否 | 一次运行的模型调用硬预算，默认 10，至少为 3 |
| `MAX_TOOL_CALLS` | 否 | 模型提出的工具调用硬预算，默认 20 |
| `MAX_TOOLS_PER_STEP` | 否 | 每个调查轮最多执行的外部工具数，默认 3，至少为 1 |
| `HITL_MODEL_CALL_THRESHOLD` | 否 | 交互模式达到多少次模型调用后请求人工确认，默认 5 |
| `HITL_TOOL_CALL_THRESHOLD` | 否 | 交互模式达到多少次工具调用后请求人工确认，默认 10 |
| `ENABLE_RUNTIME_TOOLS` | 否 | 是否向交互式 Agent 暴露预登记 Runtime/Harness 工具，默认 `false` |
| `MAX_RUNTIME_CALLS` | 否 | 一次调查最多实际执行多少个预登记检查，默认 1 |
| `RUNTIME_TIMEOUT_SECONDS` | 否 | 每次运行的全局超时上限，默认 5；会与清单超时取较小值 |

`OUTPUT_MODE=auto` 的当前策略：

- OpenAI 官方地址使用 `json_schema`；
- DeepSeek 和其他兼容服务使用更保守的 `json_object`。

`STRICT_TOOLS=auto` 的当前策略：

- OpenAI 官方地址启用严格工具 Schema；
- DeepSeek `/beta` 地址启用严格工具 Schema；
- 其他兼容服务默认关闭。

如果服务商返回：

```text
This response_format type is unavailable now
```

可以显式设置：

```env
OUTPUT_MODE=json_object
```

无论服务商是否支持原生 JSON Schema，最终文本都会经过本地 Pydantic 验证。

`api.env` 已被 `.gitignore` 排除。不要把真实密钥写入 `api.env.example`、README、评测报告或 Git 提交。

### 1.4 启动 Agent

```powershell
.venv\Scripts\python.exe main.py
```

命令行支持多行输入。粘贴完整 traceback 后，在新的 `|` 提示符处再按一次 Enter，用空行提交整段内容：

```text
> Traceback (most recent call last):
|   File "demo_app/run_case.py", line 24, in run_case
|     post_users({"email": "demo@example.com"}, create_connection())
|   File "demo_app/app/service.py", line 10, in create_user
|     user_id = payload["user_id"]
| KeyError: 'user_id'
|
```

`>` 和 `|` 是程序显示的提示符，不会发送给模型。单行问题也要再输入一个空行才会提交。输入 `exit` 或 `quit`，再输入空行，可以退出。

默认 `ENABLE_RUNTIME_TOOLS=false`，所以启动方式不变、Agent 也看不到执行工具。要演示 Runtime 人工审批流程，把自己的 `api.env` 改为：

```env
ENABLE_RUNTIME_TOOLS=true
MAX_RUNTIME_CALLS=1
RUNTIME_TIMEOUT_SECONDS=5
```

重启 `main.py` 后可以提问：“请调查并实际复现 documentation_required，再给出根因。”当模型请求运行时，程序会在任何子进程启动前显示：

```text
=== 需要人工确认 ===
选择 1批准本次运行 / 2拒绝本次运行 / 3取消调查：
```

选择 1 只批准当前预登记调用；选择 2 不执行但允许 Agent 根据静态证据继续；选择 3 取消本次调查。运行结束后建议将开关恢复为 `false`。

### 1.5 V13 稳定持久化命令

不带参数的 `main.py` 仍是原来的连续交互模式。如果要在退出程序后继续调查，使用持久化命令：

```powershell
# 0. 可选：检查 Python、依赖、api.env 和 SQLite；不会调用模型
.\.venv\Scripts\python.exe main.py doctor

# 1. 创建一次调查；遇到审批会当场询问并自动继续
.\.venv\Scripts\python.exe main.py new

# 2. 查看最近调查；这两个命令不会调用模型
.\.venv\Scripts\python.exe main.py list
.\.venv\Scripts\python.exe main.py show <调查ID>

# 3. 对等待审批的调查做决定，然后从原图节点继续
.\.venv\Scripts\python.exe main.py resume <调查ID>

# 可选：希望遇到审批就保存退出，由其他时间或其他终端处理
.\.venv\Scripts\python.exe main.py new --detach
```

`new` 遇到 Runtime 或费用审查时，Checkpoint 已经先同步写入 SQLite，然后 CLI 当场显示审批问题；用户选择后，程序在内部调用 `Command(resume=...)`，不需要复制调查 ID。恢复后若再次出现审批，会在同一终端继续询问。只有按 `Ctrl+C`、输入流结束或主动使用 `--detach` 时才需要稍后运行 `resume`。数据保存在 `.incident_state/incident_pilot.sqlite3`，该目录被 Git 和 Agent 文件工具同时忽略。

### 1.6 第一次测试 Safe Test Harness

先在 `api.env` 设置 `ENABLE_RUNTIME_TOOLS=true`，保持 `MAX_RUNTIME_CALLS=1`，再运行：

```powershell
.\.venv\Scripts\python.exe main.py new
```

粘贴下面的问题，最后多按一次 Enter：

```text
请使用 Safe Test Harness 列出可用检查，运行 demo_missing_user_id，
结合 Runtime、代码和文档证据解释根因。不要运行其他检查。
```

预期过程是：Agent 先调用无需审批的 `list_checks`，确认 ID 存在；请求 `run_check` 时程序暂停；你输入 `1` 后固定子进程才启动。结果中应出现 `check_id=demo_missing_user_id`、`exit_code=1`、`expectation_met=true` 和以 `runtime-check-` 开头的 Runtime ID。这里退出码 1 是故障成功复现，不是 Harness 自己坏了。最后报告若引用 Runtime Evidence，必须绑定该 ID。

这一步会调用你配置的模型。若只想验证本地 Harness 而不花 Token，可运行：

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_harness
```

新增自己的检查时，只编辑 `harness.json`，选择受支持 Runner 并填写固定 target；先运行 `main.py doctor` 检查清单，再让 Agent 使用它。不要把用户输入、模型输出或可变字符串写进 target。`harness.json` 是权限清单，不应当由 Agent 自动改写。

### 1.7 生成提案并进行 V13 隔离验证

补丁生成必须显式开启，否则现有调查和 Evaluation 不会多花一次模型调用：

```powershell
.\.venv\Scripts\python.exe main.py new --with-patch
```

输入完整报错，并要求先诊断再提出最小修复。系统仍先完成普通调查；只有最终报告为 medium/high、包含 Claim 和 Evidence、且通过来源验证，才会额外调用一次模型生成 `PatchProposalDraft`。随后本地校验器检查 diff，终端显示 `validated` 或 `rejected`。`--with-patch` 到这里结束，不改动任何文件，也不运行补丁后测试。

一个合格提案会展示：

```text
proposal_id
status                       # validated / rejected
diagnosis_claim_ids          # 修复对应哪些已验证结论
changed_files                # 与 diff 文件头完全一致
unified_diff                 # 只读补丁文本
rationale / risks
verification_check_ids       # 将来应用后应运行哪些 Harness 检查
validation_errors
```

不调用模型的本地验证方式：

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_patching
```

需要继续验证候选补丁的行为时，先在 `api.env` 设置 `ENABLE_RUNTIME_TOOLS=true`，再运行：

```powershell
.\.venv\Scripts\python.exe main.py new --verify-patch
```

`--verify-patch` 自动包含 `--with-patch` 的行为。提案通过结构校验后，Graph 会显示一项独立审批，列出即将运行的预登记检查。批准后系统才会：

1. 复制项目到系统临时目录，排除 `.git`、虚拟环境、密钥、缓存、报告和 SQLite 状态；
2. 在临时副本中运行补丁前基线；`reproduction` 检查必须先稳定复现原故障；
3. 只在临时副本中应用已经重新校验的 unified diff；
4. 运行补丁后检查；故障复现项必须变为成功，回归项必须保持预期结果；
5. 删除临时目录，并重新核对正式工作区目标文件的 SHA-256。

系统会自动加入所有 `covers_files` 命中修改文件的检查，以及 `covers_files=[]` 的全局回归检查。模型不能通过只选择一个宽松检查绕过契约测试。对于当前 `demo_app/app/api.py`，`api_missing_fields_contract` 会验证缺字段时返回 400 且没有调用 Service，因此“只是把 `KeyError` 换成 `ValueError`”会得到 `failed`，不会被误判为修好。

隔离验证不会再调用模型，因此相对 `--with-patch` 不增加 Token；成本只来自本地复制和预登记检查。它也不会把验证通过的补丁写回正式工作区，用户仍需审查 diff 后自行决定是否实施。

只运行 V13 本地验证测试：

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_patch_verification
```

### 1.8 长期事故记忆命令

持久化调查只有在 `stop_reason=completed`、置信度为 medium/high，且报告同时存在 Claim 和 Evidence 时，才会生成 `pending` 记忆。候选不会自动影响新调查：

```powershell
# 查看待审批记忆
.venv\Scripts\python.exe main.py memory list --status pending

# 批准后才可被新调查召回
.venv\Scripts\python.exe main.py memory approve <memory_id>

# 拒绝候选
.venv\Scripts\python.exe main.py memory reject <memory_id>

# 不调用模型，本地搜索已批准记忆
.venv\Scripts\python.exe main.py memory search KeyError user_id

# 永久删除一条记忆
.venv\Scripts\python.exe main.py memory forget <memory_id>
```

`memory list/search/approve/reject/forget` 都只操作本地 SQLite，不调用模型，不产生 Token 费用。

### 1.9 启动自检与稳定依赖

`doctor` 是一个完全本地的快速检查：验证 Python 至少为 3.10、五个直接依赖已经安装、`api.env` 和 `harness.json` 能通过校验，以及 SQLite 状态库能够打开和自动迁移。它只显示模型名、输出模式、Runtime 开关、检查数量和清单哈希前缀，绝不会打印 API Key，也不会创建模型客户端或访问网络。

```powershell
.\.venv\Scripts\python.exe main.py doctor
```

如果依赖缺失到 `main.py` 无法导入，例如再次出现 `No module named 'langgraph'`，可以直接运行只有标准库依赖的入口：

```powershell
.\.venv\Scripts\python.exe doctor.py
```

命令成功时退出码为 0，任一检查失败时退出码为 1，方便用户和自动化脚本可靠判断结果。缺少第三方包时，`doctor.py` 仍会列出全部缺失依赖，并对 `api.env`、Harness 清单和 SQLite 做基础检查，而不是跟随主程序一起导入失败。`requirements.lock` 记录当前完整测试实际使用的直接依赖版本；它不是说其他兼容版本一定不能运行，而是提供一个出现依赖差异时可回退的可重复基线。

## 2. 当前能力与边界

### 2.1 能做什么

IncidentPilot 可以：

- 从 traceback 提取文件、行号、函数和异常类型；
- 在当前项目中搜索关键词；
- 读取带行号的 UTF-8 文本文件；
- 查看有限深度的项目目录；
- 检索本地 Markdown 知识库；
- 查看 Git 状态、未提交差异和最近提交；
- 列出项目所有者预登记的安全检查，而不向模型暴露实际 target 或命令；
- 在显式启用并由用户逐次批准后，运行固定 Demo、`unittest` 或 `pytest` 检查；
- 保存退出码、预期是否满足、测试计数、失败项、异常摘要和不可伪造的系统 `runtime_id`；
- 多轮调用工具并保留观察结果；
- 显式维护可证伪候选假设、支持 Observation、反证和下一步动作；
- 将下一步动作约束为一个工具、调查目的、支持条件和否定条件；
- 每轮只执行有限数量的最高信息增益工具；
- 压缩发给模型的历史上下文，同时在 Checkpoint 保留完整调查轨迹；
- 新 Observation 未写入假设时阻止继续扩散调查；
- 在根因获得两项独立来源支持时提前停止扩散调查；
- 识别完全相同的重复工具调用；
- 在调查预算耗尽时根据已有证据强制总结；
- 在费用阈值、受保护路径或冲突假设处暂停，由用户选择继续、总结或取消；
- 使用 Checkpoint 从同一人工中断点恢复；
- 将 Checkpoint 和会话索引写入 SQLite，退出后仍可按调查 ID 恢复；
- 列出过往调查、查看等待原因、失败信息或最终报告；
- 从已落地 Evidence 的成功报告中确定性提取历史事故候选；
- 由用户批准、拒绝或删除记忆，并在新调查前召回最多 3 条相似历史；
- 记录每次调查实际召回的 Memory ID 和召回数；
- 统计 Token、上下文压缩、Observation 利用率、早停、人工确认、格式修复和受保护路径尝试；
- 为每次工具调用保存参数、来源、摘要哈希和耗时；
- 输出根因、Claim—Evidence Ledger、修复建议和置信度；
- 为合格报告生成受范围限制、绑定 Claim/Evidence 的 unified diff 提案；
- 经独立人工批准，在临时副本中执行补丁前/后的预登记检查；
- 自动选择覆盖修改文件的契约检查和全局回归检查，并输出逐项验证结果；
- 拒绝未读取文件、越界行号、伪造 Observation 和虚假 Git 提交；
- 接受纯 JSON、JSON 代码块和前后带少量说明的合法报告，并记录历次验证错误；
- 批量评测十五个故障诊断案例，其中一个强制要求 Runtime Evidence；
- 比较不同工具组合并统计多次运行稳定性。

### 2.2 不能做什么

当前版本不会：

- 执行 Agent 自己提出的任意 Shell 命令、参数或路径；
- 运行预登记列表之外的用户项目入口；
- 修改、删除或创建正式工作区中的业务代码；
- 把验证通过的修复自动写回正式工作区；
- 运行 Harness 清单之外的补丁后命令；
- 连接生产数据库或生产环境；
- 对任意外部项目动态切换调查根目录；
- 将本地 SQLite 会话在多台机器间共享；
- 将历史记忆当作当前事故的 Evidence，或仅凭历史记忆生成高置信度结论；

文件工具的根目录固定为 IncidentPilot 当前仓库。因此现阶段主要用于调查本仓库中的 `demo_app` 和项目自身代码。支持任意目标仓库需要后续增加经过验证的 workspace 参数和更严格的隔离。

## 3. 项目结构

```text
incident-pilot/
├── api.env.example             # API 配置模板
├── requirements.txt            # Python 依赖
├── requirements.lock           # 当前完整测试通过的直接依赖版本
├── main.py                     # 传统交互、持久化调查、自检和 Memory 命令
├── doctor.py                   # Python、依赖、配置、Harness 与 SQLite 自检
├── agent.py                    # Agent 公共接口、图调用与运行指标
├── session_agent.py            # 持久化调查的启动、恢复和结果组装
├── session_store.py            # SQLiteSaver、会话索引与状态转换
├── memory.py                   # 候选提取、相似度排序与安全 Memory 上下文
├── graph.py                    # LangGraph 状态、节点、路由和收尾逻辑
├── context_manager.py          # 发给模型的调查上下文选择与压缩
├── models.py                   # Pydantic 工具、报告和指标模型
├── hypotheses.py              # 假设控制工具、引用校验和证据充分度 Gate
├── provenance.py               # Observation 提取与证据来源验证
├── config.py                   # api.env 加载与供应商能力适配
├── registry.py                 # 工具注册、Schema、参数校验与执行
├── tools.py                    # 文件读取、代码搜索和目录列表
├── knowledge_tools.py          # retrieve_docs 工具
├── retrieval.py               # 本地 Markdown RAG
├── git_tools.py               # 三个只读 Git 工具
├── runtime_tools.py           # 预登记 Demo 执行、超时和 Runtime ID
├── harness.json                # 项目所有者维护的安全测试清单
├── harness.py                  # 清单校验、固定 Runner 和结构化测试结果
├── patching.py                 # unified diff 解析、范围和当前上下文校验
├── patch_verification.py       # 临时副本、基线/补丁后 Harness 与清理校验
├── .incident_state/           # Checkpoint/会话/Runtime 账本（自动生成）
├── tool_profiles.py            # Profile 工具白名单与文档路径隔离
├── evaluation.py              # 单案例确定性评分
├── experiments.py             # Profile、Case、重复运行与统计聚合
├── run_evals.py               # 真实模型评测命令行
├── knowledge/
│   ├── api.md                  # 模型输出兼容知识
│   ├── database.md             # 当前状态存储知识
│   └── troubleshooting.md      # 项目排障手册
├── demo_app/
│   ├── app/                    # 故意包含多个 Bug 的模拟业务代码
│   ├── docs/                   # RAG 专用的规范、Runbook 和事故文档
│   ├── fixtures/               # Agent 不可见的外部系统模拟器
│   ├── logs/                   # 可用于提问的简化 traceback
│   ├── checks/                 # 可由 Harness 运行的 Smoke 与业务契约检查
│   ├── evals/                  # Agent 不可见的标准答案
│   └── run_case.py             # 十二个可执行故障的入口
├── test_agent.py
├── test_context_manager.py
├── test_demo_app.py
├── test_doctor.py              # 不联网启动自检与密钥隐藏测试
├── test_evaluation.py
├── test_experiments.py
├── test_graph.py
├── test_hypotheses.py
├── test_main.py
├── test_memory.py             # 候选门槛、审批、召回、删除和证据隔离
├── test_sessions.py           # 重开、恢复和密钥隔离测试
├── test_provenance.py
├── test_runtime_tools.py
├── test_harness.py             # Harness 参数、隔离、超时、重放和真实运行测试
├── test_patching.py            # 只读补丁、Evidence 绑定和拒绝规则测试
├── test_patch_verification.py  # V13 临时应用、行为失败和工作区不变测试
├── test_tools.py
├── README.md                   # 当前版本完整说明
└── CHANGELOG.md                # 版本演进记录
```

运行时还可能生成：

```text
.incident_cache/rag_index.json  # RAG 索引缓存
.incident_reports/**/*.json     # Evaluation、正式基线与实验报告
.incident_state/incident_pilot.sqlite3  # 持久化图状态、会话、Runtime 账本和长期记忆
```

三个目录都被 Git 忽略，也不会暴露给 Agent 工具。

## 4. 从输入到报告的完整数据流

V13 有两个外层入口：`run_agent()` 使用内存 Checkpoint，适合兼容原调用方；`main.py new/resume` 使用 SQLite Checkpoint、长期 Memory、可选 Patch Proposal 和隔离验证，适合日常完整调查。两者共用同一张 LangGraph，不存在两套诊断逻辑。补丁生成和验证默认关闭；`--with-patch` 只生成提案，`--verify-patch` 同时开启提案与验证。

```text
main.py 收集一段完整多行输入
        ↓
run_agent(question) 或 start_session(question)
        ↓（仅持久化模式）
召回最多 3 条 approved Incident Memory，注入“非证据”历史线索
        ↓
agent.py 加载 api.env、解析 Tool Profile、创建模型客户端
        ↓
构建 LangGraph 并创建初始 AgentState
        ↓
call_model
        ├── context_manager 生成最小请求上下文
        │       ├── 保留原始 System 与 User 问题
        │       ├── 保留全部假设引用的 Observation
        │       └── 仅补充最近 4 条尚未引用的 Observation
        ├── update_hypotheses → 校验并替换当前完整假设集合
        ├── 普通 tool_calls → execute_tools
        │                       ├── 执行只读工具并生成 obs-xxx
        │                       ├── 提取文件、行号、Chunk 或 Commit
        │                       ├── 更新假设支持与反证
        │                       └── 检查证据充分度、硬预算和 HITL 条件
        │                                  ├── confirmed + 两项独立来源 → 提前总结
        │                                  ├── 费用阈值/冲突/保护路径 → human_review
        │                                  │                              ├── continue → 继续
        │                                  │                              ├── summarize → 总结
        │                                  │                              └── cancel → 取消
        │                                  ├── 硬预算将尽且有未归类新证据 → classify_final_evidence
        │                                  │                                  └── 仅更新假设 → 立即总结
        │                                  ├── 其他硬预算耗尽 → 强制总结
        │                                  └── 仍需调查 → call_model
        ├── run_demo_case / run_check → runtime_review
        │                   ├── approve → execute_tools → 固定 Runner → Runtime Observation
        │                   ├── deny → 不执行，生成失败 Observation 后继续
        │                   └── cancel → build_cancelled → END
        │
        └── 返回报告文本 → Pydantic + Provenance 验证
                                ├── Schema、Claim 和来源全部合法
                                │       ├── 未请求补丁 → END
                                │       └── 请求补丁 → propose_patch
                                │                           ├── 生成 PatchProposalDraft
                                │                           ├── 本地只读校验 unified diff
                                │                           ├── 保存 rejected 提案 → END
                                │                           └── validated
                                │                                  ├── 仅 --with-patch → END
                                │                                  └── --verify-patch → patch_review
                                │                                                       ├── deny/cancel → END
                                │                                                       └── approve → verify_patch
                                │                                                                    ├── 临时副本运行基线
                                │                                                                    ├── 临时应用 diff
                                │                                                                    ├── 运行契约与回归检查
                                │                                                                    └── 删除副本 → END
                                ├── 伪造来源或越界 → 带错误重试
                                ├── 可重试 → call_model
                                └── 强制总结非法 → repair_report
                                                        ├── 合法 → END
                                                        └── 仍非法 → build_fallback → END
        ↓
IncidentReport
        +
可选 PatchProposal
        +
可选 PatchVerificationResult（只在临时副本应用）
        ↓
main.py 格式化为人类可读文本
        ↓（仅 completed + medium/high + Claim/Evidence 完整）
生成 pending Incident Memory 候选，等待用户 approve/reject
```

模型本身不能直接读取磁盘或启动进程。模型只能选择注册过的工具；真正的文件、RAG、Git 和受限检查由本地 Python 函数完成。当前版本中模型先用 `list_checks` 查看公开检查，再把一个 ID 交给 `run_check`；Runtime 仍经过配置、Profile、人工授权和次数预算。最终总结和格式修复请求会收到严格 IncidentReport Schema 及逐条展开的精确 Evidence 来源白名单；无来源 Observation 不会进入白名单。若显式请求补丁，只有已通过验证的报告能进入 `propose_patch`；该节点只读取报告已经引用过的代码 Evidence，为模型提供精确当前内容、严格输出 Schema 和已登记检查 ID，然后把草稿交给本地校验器。若进一步请求隔离验证，`patch_review` 会在任何临时写入前暂停；批准后 `verify_patch` 只用确定性本地代码重新校验提案、复制项目、运行检查、应用 diff 和清理，不发生额外模型调用，也不写正式工作区。

在持久化模式中，LangGraph 每个超步的状态和 `interrupt()` 待续工作由 `SqliteSaver` 同步写盘。`incident_sessions` 表只是面向 CLI 的索引，保存问题、状态、审批请求和最终结果；图的真正恢复仍由 LangGraph Checkpoint 完成。`resume` 用同一 `thread_id` 和 `Command(resume=...)` 继续，不会把旧问题重新发给一个新 Agent。

## 5. LangGraph 控制流

### 5.1 AgentState

图中的共享状态包含：

| 字段 | 作用 |
|---|---|
| `messages` | System、User、Assistant 与 Tool 消息历史 |
| `step_count` | 调查阶段的模型请求次数 |
| `tool_call_count` | 模型提出的工具调用总数 |
| `max_steps` | 调查阶段模型请求预算，默认 8 |
| `model_call_count / max_model_calls` | 包括总结和修复在内的模型调用与硬预算 |
| `tool_call_count / max_tool_calls` | 内部控制调用与外部工具请求总量及硬预算 |
| `max_tools_per_step` | 一轮模型响应最多允许执行的外部工具数，默认 3 |
| `input/output/total_token_count` | 服务商返回的 Token 使用量；不可用时为 0 |
| `report` | 通过验证的最终报告 |
| `validation_error` | 最近一次报告格式错误 |
| `stop_reason` | `completed` 或 `invalid_synthesis` 等结束原因 |
| `tool_call_signatures` | 已实际执行的唯一工具名和规范化参数 |
| `repeated_tool_call_count` | 被拦截的完全重复调用数 |
| `force_synthesis` | 是否应该停止调查并强制总结 |
| `synthesis_attempted` | 是否已经进行过无工具总结 |
| `repair_attempted` | 是否已经进行过最后一次无工具格式修复 |
| `observations` | 系统生成的结构化工具调用轨迹，只追加不覆盖 |
| `hypotheses` | 当前完整候选根因集合，包含状态、支持 Observation 和反证 |
| `context_compaction_count` | 实际使用压缩请求上下文的模型调用次数 |
| `confirmed_at_tool_call_count` | 首次形成 confirmed 假设时的工具调用计数，用于测量确认后的浪费 |
| `hypothesis_update_required` | 新成功 Observation 是否仍待写入假设；为真时外部工具暂时关闭 |
| `hypothesis_update_failure_count` | 连续无效或越权假设更新次数；达到 2 次后停止工具调查并用现有证据总结 |
| `final_classification_attempted` | 是否已经执行过硬调查预算结束后的唯一一次受限假设归类 |
| `validation_errors` | 历次报告格式、假设准备度和 Provenance 验证错误，只追加不覆盖 |
| `evidence_sufficient / early_stopped` | 是否满足确定性证据充分度并提前收尾 |
| `human_review_*` | 是否启用 HITL、触发原因、次数和是否已经处理 |
| `cancelled` | 用户是否在人工决策点取消调查 |
| `runtime_tools_enabled` | 本次运行是否真正暴露 Runtime Schema |
| `runtime_execution_preapproved / runtime_execution_decision` | Evaluation 预授权或交互式单次审批结果 |
| `runtime_call_count / max_runtime_calls` | 已实际执行次数与硬预算 |
| `successful_runtime_call_count / runtime_timeout_count` | 成功复现与超时统计 |
| `runtime_approval_count / runtime_denial_count` | 交互式批准和拒绝次数 |
| `runtime_replay_count` | 命中已完成幂等账本、直接复用旧结果的次数 |
| `runtime_ledger_path / thread_id` | 持久化模式中的账本位置和稳定会话 ID |
| `recalled_memory_count` | 本次持久化调查实际注入的 approved 历史记忆数量；兼容入口固定为 0 |
| `generate_patch_proposal / patch_proposal` | 是否请求补丁及本地校验后的候选提案 |
| `verify_patch_proposal / patch_verification` | 是否请求隔离验证及结构化验证结果 |
| `patch_verification_decision` | 独立补丁审批的 `approve` 或 `deny` 决策 |
| `patch_verification_approval_count` | 真正允许临时写入和检查执行的次数 |

`messages` 使用追加 reducer。节点只返回新增消息，LangGraph 将其追加到完整历史；计数、报告和布尔值等字段由节点返回的新值覆盖。当前的压缩与证据保全发生在模型请求边界，不会修改这个完整状态。

每次调查默认生成新 UUID 作为 thread ID，避免不同问题共享状态。兼容函数 `run_agent()` 仍使用 `InMemorySaver`；当前 CLI 使用 `SqliteSaver`，因此关闭原 Python 进程后仍能用相同 thread ID 恢复。这种双入口设计保留旧 API，同时让 CLI 获得持久性、经过审批的长期记忆、可选补丁提案和隔离验证。

### 5.2 节点

#### `call_model`

先通过 `context_manager.py` 生成压缩请求，再把当前 Profile 的外部工具和输出格式发送给模型。`update_hypotheses` Schema 只在尚未建立初始假设，或已有新成功 Observation 等待归类时开放；成功保存假设后会暂时从 Schema 隐藏，直到外部调查产生新证据。普通压缩记忆包含完整假设、假设所引用的全部 Observation，以及最近 4 条尚未归类的 Observation；普通结果摘要最多 700 字符，成功的定向 `read_file` 摘要最多 4,000 字符，并使用紧凑行号格式确保窗口末端仍可见。两者都保留 ID、参数、成功状态和精确来源。若上一轮产生了新成功证据，请求中会追加醒目的控制门提示，模型必须先更新假设。模型先提出 2–4 个可证伪候选根因，再用最有区分度的工具验证；也可以在证据足够时直接生成最终 JSON。

当 `search_code` 已返回命中行时，Prompt 要求模型优先把命中位置附近不超过 30 行作为 `read_file` 的 `start_line/end_line`，而不是重新读取整个长文件。行号从 1 开始且包含两端；只提供 `start_line` 时自动读取从该行开始的最多 30 行。反向范围、超过 30 行的窗口和超出文件总行数的起始行在执行层拒绝。

OpenAI-compatible 严格工具 Schema 会递归把对象的全部属性加入 `required`、移除 `default` 并保留 nullable 类型。因此 DeepSeek 严格模式看到的是必填的 `path/start_line/end_line`，逻辑上的可选行号用 `null` 表示；本地 Pydantic 模型与非严格服务仍允许旧调用方省略行号。

只要完整集合中仍存在 `unverified` 或 `supported` 假设，就至少要有一个开放假设提供结构化 `next_action`：`tool_name` 表示下一项工具，`purpose` 解释信息价值，`supports_if` 和 `rejects_if` 预先声明什么结果会支持或否定它。不再要求每一个开放候选都重复规划动作，避免某个已获得支持但暂时无需继续验证的候选使整批更新失败。

#### `execute_tools`

外部工具按名称进入注册器，使用 Pydantic 校验参数并执行。每个外部调用生成唯一 `obs-xxx`，记录参数、状态、来源、摘要哈希和耗时。内部 `update_hypotheses` 不访问工作区，也不生成可用于 Evidence 的 Observation；它只能引用已经存在且成功的 Observation，并用完整集合替换图中的假设状态。已有假设时，只要一轮生成新成功 Observation，`hypothesis_update_required` 就会开启；下一轮在假设更新成功前提出的外部调用会收到 `hypothesis_update_required`，不会实际执行。反方向也有执行层保护：没有新成功 Observation 时，即使兼容服务返回未在 Schema 中声明的 `update_hypotheses`，也会收到 `hypothesis_update_not_allowed`，不能覆盖状态。首次格式错误后允许一次纠正，连续两次无效更新则立即关闭工具并进入总结。

重复调用保护先规范化工具参数，拦截完全相同的调用；对定向 `read_file` 还会把同一规范化路径的成功来源范围合并。如果新请求的每一行都已被覆盖，则生成 `repeated=true` 的失败 Observation，并在 `meta.covered_by_observation_ids` 中返回应复用的旧证据。部分重叠但包含新行的窗口、失败读取后的修正窗口都会继续执行。第一次重复仍允许模型纠正，累计第二次重复才强制总结。

工具硬预算在执行层再次检查。超过 `MAX_TOOL_CALLS` 的请求不会执行，并收到 `tool_budget_exhausted`，随后图进入总结，不能靠一次并行请求绕过预算。同一轮超过 `MAX_TOOLS_PER_STEP` 的调用收到 `per_step_tool_limit`，但不会立刻强制总结；模型下一轮可以根据已有结果重新排序，只选择信息价值最高的动作。

#### `classify_final_evidence`

调查达到步骤上限、证据充分或调查阶段的模型额度边界时，如果最后一批成功 Observation 仍未归类，系统最多进入一次受限归类。该节点复用证据保全上下文，只向模型暴露 `update_hypotheses`，不提供任何文件、RAG、Git 或 Runtime 工具；请求计入总模型调用与 Token，但不增加 `step_count`。成功或失败后都直接进入 `synthesize_report`，不会回到普通调查。

只有总模型预算至少还能容纳“受限归类、最终总结、一次格式修复”时才进入该节点。执行层会拒绝兼容服务在这里返回的任何外部工具，并记录 `final_classification_only`，因此模型无法借归类轮次额外读取文件或运行检查。

#### `runtime_review`

只有最后一条模型消息请求 `run_demo_case` 或 `run_check`、Runtime 已启用、交互式 HITL 已开启且本次没有预授权时才进入。节点调用 LangGraph `interrupt()`，把检查 ID、当前模型/工具计数和候选假设写入 Checkpoint，然后等待 `approve`、`deny` 或 `cancel`。批准只覆盖当前这批工具请求；拒绝不会启动进程，执行节点会生成一条可审计的失败 Observation；取消则直接生成取消报告。

Evaluation 没有人工输入循环，所以必须由操作者同时选择 `full_runtime` 并添加 `--allow-runtime`。该标志会作为本次评测的明确预授权，不会修改 `api.env`。

#### `propose_patch`、`patch_review` 与 `verify_patch`

`propose_patch` 是唯一会为修复额外调用模型的节点，最多调用一次。它只接收已经验证的报告和报告中真实读取过的代码，再由本地规则生成 `validated` 或 `rejected` 提案。

只有调用方显式选择 `--verify-patch` 且提案为 `validated`，图才进入 `patch_review`。这个 interrupt 与调查费用审批、Runtime 工具审批、Memory 审批彼此独立；批准只允许本次候选提案在临时目录中应用和运行界面列出的预登记检查。拒绝或取消时不会创建临时目录，也不会启动检查进程。持久化状态会显示为 `waiting_for_patch_approval`。

批准后 `verify_patch` 不调用模型。它重新对正式工作区校验 proposal ID 和 diff 上下文，要求每个修改文件至少被一个清单检查覆盖，然后复制安全子集到临时目录。基线阶段要求所有选中的 `reproduction` 检查仍能复现目标故障；临时应用 diff 后，`reproduction` 必须以 0 退出且不再命中旧故障退出码，`regression` 必须满足清单中的预期退出码。模型建议的检查、覆盖修改文件的检查以及无特定覆盖文件的全局回归都会合并运行。最后删除临时目录并比较正式目标文件的前后 SHA-256。

#### `SessionStore` 与跨进程恢复

`session_store.py` 在同一 SQLite 文件中管理四类数据：

1. LangGraph 自己的 Checkpoint 表，保存节点状态、下一节点和 interrupt 的待续工作；
2. `incident_sessions` 表，保存 CLI 需要展示的调查索引；
3. `runtime_executions` 表，保存执行型工具的幂等账本；
4. `incident_memories` 表，保存待审批、已批准或已拒绝的长期事故记忆。

会话状态只能是 `running`、`waiting_for_runtime_approval`、`waiting_for_patch_approval`、`waiting_for_human_review`、`completed`、`cancelled` 或 `failed`。`start_session()` 先建立会话索引，再以 `durability="sync"` 运行图；遇到 interrupt 就保存审批请求。`resume_session()` 只接受当前审批点允许的动作，然后用 `Command(resume=...)` 恢复。CLI 在外层循环检查 `pending_review`：正常情况下当场读取用户选择并自动调用 `resume_session()`，如果恢复后再次暂停就继续询问；`Ctrl+C`、EOF 和 `--detach` 只结束 CLI，不删除已经同步保存的状态。

Checkpoint 的序列化关闭 pickle fallback，也不允许从 MsgPack 动态导入自定义模块。这样不会因读取被篡改的本地状态而任意实例化 Python 类。`api.env` 和 API Key 不进入 AgentState、会话表或 Runtime 账本；恢复时重新从环境加载客户端配置。

#### Incident Memory 生命周期

系统将“同一次调查内的上下文”和“跨调查长期记忆”明确分开。一次持久化调查正常结束后，系统先做确定性门控：只有 `stop_reason=completed`、报告为 medium/high 置信度、至少存在一条 Claim 和一条 Evidence，而且每条 Claim 引用的 Evidence ID 都真实存在，才提取一条 `pending` 候选。低置信度、取消、失败、无证据或引用断裂的报告不会沉淀。

候选记录异常类型、关键符号、来源文件、根因摘要、解决建议和源调查 ID。它不会自动参与后续调查；用户必须使用 `memory approve` 将状态改为 `approved`，也可以 `reject` 保留审计记录或用 `forget` 永久删除。每个源调查最多生成一条候选，重复完成同一会话不会制造重复记忆。

创建新持久化调查时，系统在本机对 approved 记忆做确定性词法排序：比较异常类型、标识符、英文词和中文二元词组，并给予异常类型或关键符号精确命中额外权重，最多返回 3 条。排序不调用模型、不建立向量索引，因此搜索过程可解释且没有额外 Token 成本。

召回结果只追加到 System 上下文中的“历史候选假设”区域，并带有明确约束：它不是本次 Observation，不能直接成为 Evidence 或 Claim 的来源，也不能单独提升置信度。`Evidence.source_type` 的类型定义根本不接受 `memory`；模型仍必须用当前代码、RAG、Git 或 Runtime 工具重新验证。这样既能利用过去经验缩短调查路径，又避免错误记忆污染证据链。

#### Runtime 幂等账本

持久化模式为每个 Runtime tool call 计算稳定 `execution_id = SHA256(thread_id + tool_call_id)`。执行前使用 SQLite `BEGIN IMMEDIATE` 原子领取执行权：

- 没有记录：写入 `running`，然后真正执行；
- 已是 `completed`：返回上次的结构化结果，不启动第二个子进程；
- 仍是 `running`：说明上次可能在执行后、记录结果前崩溃。系统无法证明副作用没发生，因此拒绝自动重跑。

这是“安全的 at-most-once 倾向”，不是数学上无条件 exactly-once。外部进程和 SQLite 无法共享一个原子事务；当成功结果不确定时，宁可让人介入，也不猜测并重复执行。

#### `human_review`

交互式 `main.py` 会在以下情况使用 LangGraph `interrupt()` 暂停：达到模型或工具费用阈值、尝试受保护路径、出现多个高置信度 confirmed 假设。状态由 Checkpointer 保存，用户可以选择继续调查、使用已有证据总结或取消；`agent.py` 使用 `Command(resume=...)` 从同一个节点恢复。Evaluation 默认关闭 HITL，避免批处理等待输入。

#### 证据充分度 Gate

只有状态为 `confirmed`、置信度至少 0.8、没有反证，并绑定至少两个成功 Observation 的假设才可能提前停止；两项 Observation 还必须来自不同来源类型，或至少两个不同文件。单条线索和模型自报 high confidence 都不足以触发早停。

#### `validate_report`

先使用 `IncidentReport.model_validate_json()` 验证模型输出，再检查 Claim 引用、Observation 是否存在、工具是否成功、来源类型、文件、行号范围和 Git 提交。任何一项不匹配都会把具体错误加入消息，让模型根据真实 Observation 修正，而不是接受“文件确实存在但模型没有读过”的引用。

#### `synthesize_report`

证据充分、达到调查/模型/工具硬预算，或第二次发现完全重复调用后，系统会在可用且必要时先完成最后证据归类，随后不再向模型提供工具，只要求它使用现有 Observation 和假设生成报告；预算不足以安全归类时则直接总结。此时上下文切换为证据保全模式：纳入全部具有真实来源的成功 Observation、全部假设引用和最近两条失败结果，避免关键但尚未绑定的旧证据被普通窗口淘汰。报告契约把每个真实来源展开为一个完整可复制的 Evidence 白名单对象；无来源 Observation 不会成为候选。这次请求不计入调查 `step_count`，但计入总模型调用与 Token。

#### `repair_report`

如果无工具强制总结仍未通过 Pydantic 或 Provenance 验证，系统会再提供一次不带工具的严格 JSON 格式修复机会。修复请求包含具体字段路径、错误原因、上一次报告和扁平精确来源白名单，并明确要求在缺少 confirmed 假设时降低置信度；与白名单不匹配的旧 Evidence 必须整项替换或删除，不能只更换文件或行号后保留错误 Observation ID，未被 Claim 使用的 Evidence 也必须删除。它不允许重新调查，避免已经取得的 Git 或代码证据因为一次格式错误全部丢失。

#### `build_fallback`

如果最后一次格式修复仍不符合要求，系统优先从最高置信度的 supported/confirmed 假设及其真实支持 Observation 构造有来源的降级报告；没有可用假设时才返回通用低置信度说明。结束原因仍为 `invalid_synthesis`，Evaluation 不会把降级结果伪装成正常通过。

#### `build_cancelled`

用户在 HITL 节点选择取消时，不再请求模型，直接生成低置信度取消报告，并以 `stop_reason=cancelled` 结束。

### 5.3 多层成本与循环保护

第一层是业务预算：

```python
max_steps = 8
```

它控制允许使用工具的调查轮数。除此以外，系统还分别限制总模型调用、总工具调用、单轮工具调用、Runtime 调用次数和单次 Runtime 超时。没有假设时，模型硬预算预留总结和格式修复两次请求；已有假设时，预留受限归类、总结和格式修复三次请求。受限归类计入总模型调用与 Token，但不占调查 `step_count`，也不能调用外部工具。每次请求再通过确定性上下文选择器控制重复输入量。长期记忆的筛选和排序完全在本地完成，不额外请求模型。可选补丁提案最多增加一次无工具模型调用。最后由 LangGraph `recursion_limit` 限制节点跳转总数。这些计数对象不同，不能互相替代。

LangGraph 框架保险为：

```python
recursion_limit = max_steps * 4 + 8
```

它限制节点跳转总数，防止图结构异常循环。两者统计对象不同，不能互相替代。

### 5.4 重复调用保护

工具签名采用：

```text
工具名 + 规范化后的 JSON 参数
```

JSON 参数会按键名排序，因此以下调用被视为相同：

```json
{"query":"user_id","path":"."}
{"path":".","query":"user_id"}
```

完全相同的调用不会再次执行，而是返回 `duplicate_tool_call`。第一次重复后，模型还有一轮机会使用已有结果、改查其他证据或直接输出报告；同一次调查中第二次重复才触发强制总结。语义相似但参数不同的调用目前不会被识别，例如搜索 `user_id` 和搜索 `missing user_id` 仍被视为两次不同调查。

## 6. 工具注册与八个受控工具

### 6.1 ToolRegistry

每个工具注册时提供：

- 工具名；
- 用途说明；
- Pydantic 参数模型；
- 实际 Python 函数。

注册器负责：

1. 防止工具重名；
2. 生成发给模型的 Function Calling Schema；
3. 按 Profile 筛选可见 Schema；
4. 严格校验模型参数；
5. 拒绝当前 Profile 不允许的调用；
6. 将成功和错误统一转换成 `ToolResult` JSON。

统一结果格式：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {}
}
```

工具失败也作为 Observation 返回给模型，而不是直接让整个 Agent 崩溃。

### 6.2 文件工具

| 工具 | 参数 | 行为与限制 |
|---|---|---|
| `read_file` | `path, start_line, end_line` | 读取项目内 UTF-8 文件并保留原始行号；行号均为包含端点，定向窗口最多 30 行，两个行号为 `null` 时兼容整文件读取，结果最多 20,000 字符 |
| `search_code` | `query` | 在允许的文本后缀中大小写不敏感搜索，最多 50 条匹配 |
| `list_files` | `path`、`max_depth` | 列出目录和文件，深度 1–5，最多 200 项 |

底层搜索后缀包括 Python、Markdown、文本、JSON、TOML、YAML；但正常 Agent 运行总会激活 Profile，因此 Markdown 会被路径策略过滤，只能经 RAG 获取。文件路径在解析后必须仍位于项目根目录内。

### 6.3 RAG 工具

`retrieve_docs(query, top_k)` 在本地知识库中返回最多 1–5 个相关片段。返回字段包括：

```text
chunk_id
source
section
line_start
line_end
content
score
```

### 6.4 Git 工具

| 工具 | 行为 |
|---|---|
| `git_status()` | 查看当前分支和工作区改动 |
| `git_diff(path)` | 查看一个指定现有非文档文件的未提交差异；拒绝目录和点号 |
| `git_log(limit)` | 查看最近 1–20 条提交的哈希、作者、时间和标题 |

Git 工具只使用预先定义的参数列表，`shell=False`，超时 8 秒，输出最多 20,000 字符。它们不会执行提交、重置、切换分支或修改工作区。

### 6.5 Safe Test Harness

当前有两个 Harness 工具：

| 工具 | 模型可以提供什么 | 作用 |
|---|---|---|
| `list_checks()` | 无参数 | 列出检查 ID、Runner、说明、超时和预期退出码；不暴露真实 target 或命令 |
| `run_check(check_id)` | 仅一个已登记 ID | 运行对应固定检查并返回结构化 Runtime Observation |

安全清单保存在 `harness.json`。每一项包含 `check_id`、`runner`、`target`、`description`、`timeout_seconds` 和 `expected_exit_codes`。当前 Runner 有三种：

- `demo_case`：target 必须属于十二个固定故障案例；
- `unittest`：target 必须是合法的 Python 模块名，不能附加参数；
- `pytest`：target 必须是仓库内已经存在的 Python 文件或目录，不能越界或使用通配符。

项目默认不额外依赖 `pytest`，因为当前预登记检查只使用 `demo_case` 和标准库 `unittest`。只有你在清单中新增 `pytest` 检查时，才需要在自己的环境中安装 pytest；未安装时会得到结构化的测试失败，而不会回退到 Shell 或自动联网安装。

清单是项目所有者维护的受信配置，不是模型生成的内容。Agent 的文件工具会隐藏 `harness.json`，并且没有写文件工具；模型只能通过 `list_checks` 看见经过裁剪的公开字段。加载清单时还会检查版本、字段、重复 ID、数量、退出码范围、路径边界，以及是否指向 `evals`、`fixtures`、缓存、状态库或 Harness 自身测试等内部区域。模型调用 Schema 只有 `check_id`，即使尝试额外传 `command`、`args`、`path`、`cwd` 或 `env` 也会被严格参数验证拒绝。

真正执行时，系统依据 Runner 构造以下三种参数数组之一：

```text
<current-python> -m demo_app.run_case <固定案例>
<current-python> -m unittest -q <固定模块>
<current-python> -m pytest -q <固定仓库内目标>
```

所有调用都使用 `shell=False`，工作目录固定为仓库根目录，子进程只继承启动所需的最小环境，不继承 `API_KEY`。实际超时取 `harness.json` 的单项超时与 `RUNTIME_TIMEOUT_SECONDS` 的较小值；因此清单写 30 秒而全局上限是 5 秒时，仍会在 5 秒停止。标准输出和错误输出会截断、绝对路径会脱敏，结果统一包含 `exit_code`、`expectation_met`、测试通过/失败数量、失败测试名、异常类型、异常消息、traceback 帧和 Runtime ID。

`expected_exit_codes` 解决了“非零退出码不一定代表 Harness 失败”的问题。例如故障复现案例本来就应该抛出异常并以 1 退出；此时 `exit_code=1` 且 `expectation_met=true`，表示预期故障被成功复现。测试套件通常期望 0。超时或进程无法启动才返回工具级失败。

清单原文和每个检查定义都会计算 SHA-256。幂等账本把检查 ID 与定义哈希共同绑定：同一审批点恢复时，已完成结果直接安全重放；如果项目所有者改变了检查定义，它会成为不同执行对象，不会把旧结果误当作新结果。每次运行生成的 `runtime_id` 被写入 Observation；最终 `source_type=runtime` 的 Evidence 必须引用同一 Observation 和同一 Runtime ID，模型编造的 ID 无法通过来源验证。

旧工具 `run_demo_case(case_id)` 继续保留，避免 V9/V10 的调用方和评测失效；新调查应优先使用 `list_checks` + `run_check`。两种执行工具共用同一个配置开关、`full_runtime` Profile、人工审批节点、Runtime 次数预算、全局超时、指标和 SQLite 幂等账本。

### 6.6 V13 Patch Proposal 与 Sandbox Verification

Patch Proposal 不是 Agent 工具，而是最终报告验证成功后的可选 Graph 节点。这样模型在调查阶段不能借“生成补丁”绕过工具和证据约束，也不会把补丁草稿误当成当前代码。

模型只生成 `PatchProposalDraft`：

```text
diagnosis_claim_ids[]       修复对应的报告 Claim
changed_files[]             声明要修改的文件，最多 3 个
unified_diff                标准 unified diff，最多 50,000 字符
rationale                   为什么这处修改能解决根因
risks[]                     兼容性和行为风险
verification_check_ids[]    应使用的已登记 Harness 检查
```

`proposal_id`、`status` 和 `validation_errors` 由本地系统生成，模型不能自行宣称“已经验证”。确定性校验包括：

1. Claim 必须真实存在且已经绑定 Evidence；
2. diff 中的文件必须与 `changed_files` 完全一致；
3. 只能修改最多 3 个已经存在的 Python 文件，增删总量不超过 120 行；
4. 每个修改文件必须已经出现在本次报告的代码 Evidence 中；
5. 禁止创建、删除、重命名、二进制补丁、路径越界和通配式目标；
6. 禁止修改测试、`harness.json`、Harness/Evaluation、API 配置、夹具、缓存和状态库；
7. 每个 `@@` hunk 声明的旧/新行数必须准确，旧内容必须逐行匹配当前磁盘文件；
8. `verification_check_ids` 必须真实存在于当前 Harness 清单。

全部满足时状态为 `validated`；否则状态为 `rejected` 并列出具体原因。`validated` 只证明它是一个当前可审查、范围受控、上下文匹配的候选 diff，并不能证明业务语义正确。`--with-patch` 仍在这里结束，保持 V12 的只读兼容行为。

当服务商支持 `json_schema` 时，请求使用原生严格 Schema；DeepSeek 等只提供 `json_object` 的兼容接口只能保证“这是 JSON”，不能保证字段名正确。V13 因此还把由 Pydantic 模型实时生成的 Schema 放进最终报告、格式修复和补丁请求：报告请求额外列出可引用 Observation 与精确来源，补丁请求额外提供六字段示例、禁止字段，以及每个 Harness ID 的 `purpose` 和 `covers_files`。Schema 由模型类生成而不是复制两套定义，后续字段变化不会让提示与本地校验器悄悄失步。最终本地 Pydantic、Provenance、diff 和 Harness 结果校验仍是唯一可信边界。

`--verify-patch` 在 `validated` 后进入独立审批。批准后系统在临时副本运行基线、应用 diff、运行补丁后检查并删除副本。模型选择的检查只是建议；系统还会强制加入覆盖每个修改文件的检查和全局回归，且没有覆盖声明的文件直接拒绝验证。最终 `PatchVerificationResult.status` 有 `verified`、`failed`、`rejected` 或 `denied`，并保存每个检查的阶段、退出码、预期是否命中、成功条件、测试计数、失败项、输出摘要、超时和耗时。

成本方面，普通 `main.py`、`main.py new`、现有 Evaluation 和 `run_agent()` 默认行为不变。只有 `--with-patch`、`--verify-patch` 或对应 API 参数才多执行最多一次无工具模型请求；隔离验证本身不调用模型，不增加 Token，只消耗本地复制与 Harness 时间。低置信度、没有 Claim/Evidence 或没有代码 Evidence 时由本地规则直接跳过，不消耗补丁生成调用。

## 7. 本地 RAG 原理

### 7.1 数据源

RAG 只索引：

```text
knowledge/**/*.md
demo_app/docs/**/*.md
```

它不索引源代码、日志、`evals/`、`api.env` 或历史评测报告。源代码由文件工具调查；标准答案必须与 Agent 隔离。

### 7.2 切块

Markdown 首先按 `#` 到 `######` 标题切成章节。超过 900 字符的章节再使用滑动窗口切分，窗口重叠 120 字符，降低跨边界信息丢失。

每个 Chunk 保存来源文件、标题、起始行、正文和稳定 ID。

### 7.3 向量与检索

当前 RAG 不使用外部 Embedding API，也不下载大型模型。它提取：

- 英文单词和代码标识符；
- 中文单字；
- 中文双字组合。

每个 Token 通过 BLAKE2b 稳定哈希映射到 512 维向量，并进行归一化。查询与 Chunk 使用余弦相似度排序，只返回正相关且分数最高的 `top_k` 项。

这是一种轻量、免费、可离线复现的检索方法，适合当前小型知识库，但语义能力弱于真正的 Embedding 模型。

### 7.4 缓存失效

所有知识文件的相对路径和内容共同生成 SHA-256 指纹。缓存指纹一致时复用 `.incident_cache/rag_index.json`；文档新增、删除或内容变化后，指纹变化并自动重建索引。

## 8. Hypothesis- and Evidence-Driven Diagnosis

### 8.1 Diagnostic Hypothesis

模型通过内部控制工具维护以下结构：

```text
DiagnosticHypothesis
├── hypothesis_id
├── statement
├── status                    # unverified / supported / rejected / confirmed
├── confidence                # 0.0–1.0
├── supporting_observation_ids[]
├── contradicting_observation_ids[]
└── next_action
```

`supported` 和 `confirmed` 必须至少引用一条成功 Observation，`rejected` 必须引用反证；不存在或失败的 Observation 不能改变假设状态。模型每次提交的是当前完整集合，这使状态可 checkpoint、可评测，也避免只从自然语言 Thought 猜测 Agent 当前相信什么。

最终报告还有状态门槛：`high` 必须至少存在一个 `confirmed` 假设，`medium` 必须至少存在一个 `supported` 或 `confirmed` 假设；只有 `low` 可以在没有已支持假设时诚实结束。假设状态不替代 V7 的 Claim—Evidence Provenance，二者会分别验证。

### 8.2 Tool Observation

每次工具调用都会生成由系统控制的 `ToolObservation`：

```text
ToolObservation
├── observation_id       # obs-001
├── tool_call_id         # 模型调用 ID
├── step                 # 调查轮次
├── tool_name
├── arguments            # 已解析参数
├── ok / repeated
├── sources[]            # 实际观察到的文件、行、Chunk 或 Commit
├── error
├── result_sha256        # 带 Observation ID 的结果摘要哈希
├── result_excerpt       # 普通结果最多 1000 字符；定向文件窗口最多 4000 字符
└── duration_ms
```

`read_file` 生成文件行号范围，`search_code` 生成每个命中行，`retrieve_docs` 生成文档 Chunk 和起止行，`git_log` 生成 Commit，`git_diff` 生成文件与 Diff Hunk。失败或重复调用也有 Observation，但 `ok=false`，不能作为支持性证据。

### 8.3 Claim—Evidence Ledger

最终报告结构为：

```text
IncidentReport
├── summary
├── root_cause
├── claims[]
│   ├── claim_id
│   ├── statement
│   └── evidence_ids[]
├── evidence[]
│   ├── evidence_id
│   ├── observation_id
│   ├── source_type
│   ├── file
│   ├── line_start / line_end
│   ├── commit_hash
│   └── description
├── suggested_fixes[]
└── confidence
```

代码、文档和运行日志证据必须填写真实文件与已观察行号。Git Commit 证据使用 `commit_hash`，文件留空、行号填 `null`。每条 Claim 必须引用存在的 Evidence；`medium` 或 `high` 报告必须至少包含一个有证据的 Claim。

### 8.4 确定性来源验证

`provenance.py` 在接受报告前检查：

1. Claim ID 和 Evidence ID 唯一；
2. Claim 引用的 Evidence 全部存在；
3. Evidence 引用的 Observation 真实存在且工具执行成功；
4. `source_type` 与工具结果一致；
5. 文件和行号落在该 Observation 的真实返回范围；
6. Git 短哈希能够匹配 `git_log` 返回的完整 Commit；
7. 不允许存在未被任何 Claim 使用的游离 Evidence。

这能证明“模型确实观察过所引用的位置”，但还不能仅靠确定性代码判断一段证据在语义上是否充分支持自然语言 Claim。语义支持、反证和置信度校准仍属于后续混合评测范围。

## 9. Demo App：确定性故障夹具

`demo_app` 是供 IncidentPilot 调查的模拟业务系统，不是生产应用。Bug 被故意保留，目的是生成稳定、真实、可评分的故障。故障源码不使用直接写明答案的 `BUG-xxx` 注释，以降低答案泄漏。

### 9.1 缺少输入校验

```powershell
.venv\Scripts\python.exe -m demo_app.run_case missing_user_id
```

预期：

```text
KeyError: 'user_id'
```

调用链为 `run_case → post_users → create_user → payload["user_id"]`。API 层没有校验必填字段，Service 直接使用字典下标。

### 9.2 数据库迁移不一致

```powershell
.venv\Scripts\python.exe -m demo_app.run_case schema_mismatch
```

预期：

```text
sqlite3.OperationalError: table users has no column named user_id
```

数据库已经使用 `external_id`，Repository 的 INSERT 仍写入旧字段 `user_id`。

### 9.3 异常路径连接泄漏

```powershell
.venv\Scripts\python.exe -m demo_app.run_case connection_leak
```

预期：

```text
RuntimeError: connection pool exhausted
```

Worker 获取连接后在无效任务分支抛出异常，没有执行 `release`。连续失败后活动连接达到上限。

### 9.4 供应商文档约束

```powershell
.venv\Scripts\python.exe -m demo_app.run_case documentation_required
```

预期：

```text
RuntimeError: HTTP 422: timeout_policy_violation
```

应用把 `WEBHOOK_TIMEOUT_SECONDS` 配置为 30，但外部供应商 Acme Notify v2 的契约规定 `timeout_seconds` 最大为 10。供应商限制位于 Agent 不可见的运行夹具中；Agent 必须通过 RAG 查询 `demo_app/docs/integrations.md` 才能获得准确上限。

以上四个命令应该以非零状态退出。这里“测试成功”的含义是故障按预期稳定复现，而不是业务代码正确。

也支持直接脚本启动：

```powershell
.venv\Scripts\python.exe demo_app\run_case.py missing_user_id
```

入口会在直接脚本模式下补充项目根目录，避免 `No module named 'demo_app'`。模块方式仍然是推荐用法。

## 10. 确定性 Evaluation

### 10.1 标准答案

`demo_app/evals/*.json` 包含：

```text
case_id
question
expected_exception
root_cause_keywords
evidence_files
relevant_docs
requires_runtime_evidence
```

只有 `question` 发送给 Agent，其他字段由评测器保存并用于评分。`evals/`、评测实现和对应测试均对 Agent 隔离；`git_diff` 必须指定单个现有代码文件，不能再用点号读取整个工作区并绕过隔离。

### 10.2 单案例评分

评测器计算：

- 异常类型是否在报告出现；
- 根因关键词命中率；
- 标准代码文件命中率；
- 相关文档命中率；
- 引用文件与行号有效率；
- Evidence Observation 落地率；
- Claim 证据覆盖率；
- Provenance 违规数量；
- 是否满足 Case 明确要求的 Runtime Evidence。

当前硬通过条件是：

```text
根因关键词命中率 = 100%
并且核心代码文件命中率 >= 50%
并且无效本地引用数 = 0
并且 Evidence Observation 落地率 = 100%
并且 Claim 证据覆盖率 = 100%
并且 Provenance 违规数 = 0
并且（若 requires_runtime_evidence=true）至少有一条已落地 Runtime Evidence
并且 stop_reason = completed
```

根因关键词在 `summary + root_cause + claims[].statement` 中匹配。Claim 是经过 Evidence 绑定的正式诊断结论，因此其中的精确配置值计入根因评分；修复建议和证据描述仍不参与，避免模型在非结论区域堆关键词。文档命中、异常类型和模型置信度是观察指标，不是硬门槛。

相关文档只有在对应 Evidence 绑定到真实 `retrieve_docs` Observation，并且该 Observation 确实返回了目标文档片段时才计分。仅调用一次 RAG 或猜中文档路径都不算命中。数值型根因标准使用带单位的短语，例如 `10 秒`，避免代码中的“第 10 行”被误判为正确阈值。

引用验证同时检查本地物理位置和本次工具 Observation：文件不仅要存在，模型还必须真正读取过对应行；Git 提交必须真实出现在绑定的 `git_log` 结果中；Runtime ID 必须来自绑定的 `run_demo_case` 或 `run_check` Observation。

### 10.3 运行指标

`run_agent_detailed()` 返回：

```text
AgentRunResult
├── report: IncidentReport
├── metrics: RunMetrics
├── observations[]: ToolObservation
├── hypotheses[]: DiagnosticHypothesis
├── validation_errors[]: 历次报告验证错误
├── patch_proposal: PatchProposal | null
├── patch_validation_errors[]: 补丁格式或安全验证错误
└── patch_verification: PatchVerificationResult | null
```

`RunMetrics` 包含：

| 字段 | 含义 |
|---|---|
| `tool_profile` | 本次工具组合 |
| `model_call_count` | 包括强制总结和格式修复在内的模型请求总数 |
| `investigation_step_count` | 可以使用工具的调查模型轮数 |
| `tool_call_count` | 模型提出的工具调用总数 |
| `unique_tool_call_count` | 实际执行的唯一外部工具调用数；不包含内部假设状态更新 |
| `repeated_tool_call_count` | 被去重保护拦截的数量 |
| `observation_count` | 成功、失败和重复调用生成的 Observation 总数 |
| `successful_observation_count` | 成功执行且非重复的 Observation 数量 |
| `synthesis_used` | 是否使用强制总结 |
| `format_repair_used` | 是否进行过最后一次无工具格式修复 |
| `final_classification_count` | 硬调查预算结束后是否执行过唯一一次受限假设归类，取值为 0 或 1 |
| `early_stopped` | 是否在调查轮数、模型和工具硬预算之前，因 confirmed 假设证据充分而提前总结 |
| `hypothesis_count / confirmed_hypothesis_count` | 最终假设总数和已确认数量 |
| `human_review_count` | LangGraph HITL 人工决策次数 |
| `protected_access_attempt_count` | 被安全边界拦截的保护路径访问次数 |
| `input/output/total_token_count` | 服务商返回的 Token；服务商不提供时为 0 |
| `context_compaction_count` | 使用压缩调查记忆请求模型的次数 |
| `unreferenced_successful_observation_count` | 运行结束时既未被假设也未被最终报告使用的成功 Observation 数 |
| `observation_utilization_rate` | 被假设或最终 Evidence 使用的成功 Observation 比例；无成功 Observation 时为 1 |
| `post_confirmation_tool_call_count` | 首次形成 confirmed 假设后仍提出的工具调用数 |
| `runtime_call_count / successful_runtime_call_count` | 实际执行的 Runtime 次数和成功取得结果的次数 |
| `runtime_timeout_count` | 因超时终止的 Runtime 次数 |
| `runtime_approval_count / runtime_denial_count` | 交互式 Runtime 批准和拒绝次数 |
| `recalled_memory_count` | 本次调查实际召回并注入的 approved Incident Memory 数量 |
| `patch_requested` | 调用方是否显式请求当前版本的补丁提案 |
| `patch_proposal_generated / patch_proposal_valid` | 是否生成提案，以及是否通过本地确定性校验 |
| `patch_verification_requested` | 调用方是否显式请求 V13 隔离验证 |
| `patch_verification_approval_count` | 用户批准临时验证的次数 |
| `patch_verification_check_count` | 基线与补丁后实际运行的检查总次数 |
| `patch_verified` | 是否得到 `verified` 结果 |
| `tool_names` | 按请求顺序记录的工具名 |
| `stop_reason` | 图结束原因 |
| `duration_ms` | `app.invoke()` 的墙钟耗时 |

普通 `run_agent()` 仍然只返回 `IncidentReport`，保持现有调用方兼容。

## 11. 工具消融、Runtime Evidence、成本与稳定性实验

### 11.1 四种 Profile

| Profile | 可用工具 | 实验目的 |
|---|---|---|
| `code_only` | 三个文件工具；不能直接看到 RAG 文档 | 验证只看代码和日志是否足够 |
| `code_rag` | 文件工具 + RAG；文档只能经 RAG 获取 | 测量项目文档的贡献 |
| `full` | 文件工具 + RAG + Git；文档只能经 RAG 获取 | 测量 Git 上下文的额外贡献 |
| `full_runtime` | `full` + `list_checks`、`run_check` 和兼容 `run_demo_case` | 调查需要真实复现或测试证据的案例 |

Profile 使用三层基础限制：模型只收到允许的工具 Schema，执行节点拒绝白名单外调用，文件工具再实施路径级隔离。启用任一 Profile 后，所有 Markdown 都不会出现在 `list_files` 和 `search_code` 结果中，`read_file` 也会拒绝直接读取；RAG Profile 必须调用 `retrieve_docs` 获取已建立索引的 `knowledge/` 与 `demo_app/docs/` 文档。`demo_app/fixtures/` 对所有 Agent Profile 都不可见。

交互式命令行选择 `full_runtime`，但 `ENABLE_RUNTIME_TOOLS=false` 时会在构图前移除 Runtime Schema，此时实际能力等同 `full`。开启后仍需要每次人工批准。普通 `--compare` 有意只比较 `code_only`、`code_rag`、`full`，不会悄悄增加可执行实验。

### 11.2 十五个案例的分工

| Case | 集合 | 主要目的 |
|---|---|---|
| `missing_user_id` | development | 基础 API 调用链诊断 |
| `async_missing_await` | development | 异步调用与返回值契约诊断 |
| `retry_non_idempotent` | development | 支付响应丢失与重试契约诊断 |
| `schema_mismatch` | development | 基础数据库字段不一致诊断 |
| `connection_leak` | development | 基础异常路径资源泄漏诊断 |
| `documentation_required` | hidden | 没有供应商文档就无法知道准确的 10 秒约束 |
| `timezone_mismatch` | hidden | 时区 offset 被丢弃后的 SLA elapsed time 误判 |
| `cache_key_version` | hidden | 缓存读写双方使用不同 Key 版本 |
| `pagination_off_by_one` | hidden | 1-based 页码换算时跳过第一页记录 |
| `config_env_rename` | hidden | 部署模板改名后应用仍读取旧环境变量 |
| `transaction_rollback` | hidden | 失败批次错误提交部分写入而没有回滚 |
| `dependency_contract_change` | hidden | SDK v3 关键字参数迁移后的适配层不兼容 |
| `git_regression` | challenge | 已知连接泄漏根因的 Git 历史变体 |
| `misleading_documentation` | challenge | 已知连接泄漏根因的误导文档变体 |
| `runtime_required` | runtime | 实际复现并引用 Runtime ID |

`git_regression` 和 `misleading_documentation` 复用 development 中的连接泄漏，属于工具能力挑战题，不计作未见故障泛化。hidden set 当前包含供应商文档、跨时区计算、缓存 Key 版本、分页边界、环境变量改名、事务回滚和 SDK 契约变化七个未参与 V13/V14.3 调优的故障。`git_regression` 依赖仓库历史；如果导出项目时丢失 `.git`，Git 组无法取得标准提交哈希。`runtime_required` 没有 Runtime Evidence 时必定失败。

### 11.3 运行实验

默认组合是五个 development Case、`full` Profile、每个一次。费用保护会在模型调用前阻止未带 `--yes` 的五次实验：

```powershell
.\.venv\Scripts\python.exe run_evals.py
```

日常先用 `--case` 运行一个 development 案例。hidden 案例必须显式选择 `--split hidden`，避免在调试时意外查看结果；挑战题和 Runtime 题分别使用 `challenge`、`runtime`。

干净工作区上的 V13 development 基线命令为：

```powershell
.\.venv\Scripts\python.exe run_evals.py `
  --split development `
  --profile full `
  --runs 1 `
  --baseline-label v13 `
  --yes
```

`--baseline-label` 要求 Git 工作区干净，报告写入 `.incident_reports/baselines/<label>/`，已有文件永不覆盖。JSON 内同时记录 Agent 基线提交、当前仓库提交、Benchmark/案例摘要哈希、集合、案例顺序、模型、输出模式、工具严格模式、调用预算、步数和时间；温度标记为当前实现的 `provider_default`。

最低成本的 Runtime 专项评测只有一次真实 Agent 调查，并且必须显式声明本次允许执行预登记案例：

```powershell
.\.venv\Scripts\python.exe run_evals.py `
  --split runtime `
  --case runtime_required `
  --profile full_runtime `
  --allow-runtime
```

`--allow-runtime` 同时负责暴露工具和为这次非交互评测预授权。没有该参数时，选择 `full_runtime` 会在调用模型前直接退出；其他 Profile 即使误加该参数也没有 Runtime Schema。

2026-09-13 的 V9 单案例验收基线为：`runtime_required + full_runtime` 通过 1/1，根因、代码、文档、引用、Evidence 落地和 Claim 覆盖均为 100%，Provenance 违规为 0；Runtime 1/1 成功、超时 0，confirmed 假设触发早停，模型调用 8 次、工具调用 10 次、总 Token 38,821。该数字来自当次所用模型与服务商，只用于回归参考，不代表其他模型必然得到相同成本。

最低成本的三组烟雾对照：

```powershell
.\.venv\Scripts\python.exe run_evals.py --case missing_user_id --compare
```

指定一个 Profile：

```powershell
.venv\Scripts\python.exe run_evals.py --profile code_only
```

选择两个 Profile：

```powershell
.venv\Scripts\python.exe run_evals.py `
  --profile code_only `
  --profile code_rag
```

比较全部 Profile：

```powershell
.venv\Scripts\python.exe run_evals.py --compare
```

每个组合重复三次：

```powershell
.\.venv\Scripts\python.exe run_evals.py --compare --runs 3 --yes
```

development 的标准三种 Profile × 五个 Case × 三次等于 45 次 Agent 调查；每次调查内部又可能请求模型多次。不要把矩阵当作烟雾测试：先跑一个静态案例的三组对照，再单独跑一次 Runtime Case，最后才按研究需要增加重复次数。

推荐的 challenge 对照有 6 次，必须显式确认：

```powershell
.venv\Scripts\python.exe run_evals.py `
  --split challenge `
  --compare `
  --yes
```

其他参数：

```text
--case CASE_ID       只运行指定案例，可重复
--split SPLIT        development、hidden、challenge、runtime 或 all
--max-steps N        每次调查的模型轮数预算
--profile PROFILE    选择 Profile，可重复
--compare            使用全部三种 Profile
--runs N             每个组合重复 1–10 次
--output PATH        自定义 JSON 输出路径
--baseline-label ID  保存不可覆盖的正式基线；要求工作区干净
--yes                显式确认超过 3 次真实 Agent 调查
--allow-runtime      预授权 full_runtime 执行预登记 Demo Case
```

`--compare` 和 `--profile` 互斥。开始前程序会打印即将进行的 Agent 调查总数。

### 11.4 输出层级

JSON 报告默认保存到：

```text
.incident_reports/eval-YYYYMMDD-HHMMSS.json
```

结构为：

```text
ExperimentRun
├── profiles
├── runs_per_case
├── attempts             # 每次独立报告、指标、Observation 轨迹和得分
├── case_summaries       # Profile + Case 的重复运行稳定性
├── profile_summaries    # 每个 Profile 的综合表现
└── overall_summary      # 整次实验汇总
```

终端逐次结果额外显示“落地、Claim、违规、假设、早停、利用、压缩、Token”。“利用”是成功 Observation 最终进入假设或报告证据的比例，“压缩”是本次运行采用最小上下文的模型请求次数。失败案例随后显示机器可读原因，例如缺失根因关键词、未落地证据、无证据 Claim、Provenance 违规或异常停止原因。之后显示 Profile 对照；当 `runs > 1` 时还显示按案例稳定性。

每个 `attempts[]` 都持久化本次完整 `observations[]`、`hypotheses[]` 和 `validation_errors[]`。因此实验结束后既能复核 Evidence 引用的 Observation、工具参数、真实来源范围和执行状态，也能看到每一次报告为何被 Pydantic、假设准备度或 Provenance Validator 拒绝。

### 11.5 聚合指标

每个 Profile 汇总：

- 运行数、通过数、通过率；
- 根因、代码、文档、引用、Evidence 落地率和 Claim 覆盖率的平均值与总体标准差；
- Provenance 违规总数；
- 模型调用和工具调用的平均值与总体标准差；
- 重复工具调用总数；
- confirmed 假设平均数、证据充分早停次数与比例；
- 上下文压缩平均次数、Observation 利用率平均值与总体标准差；
- 未引用成功 Observation 总数、确认根因后的额外工具调用总数；
- 人工确认和受保护路径尝试次数；
- Runtime 请求、成功、超时、批准、拒绝和幂等重放次数；
- approved 历史记忆召回次数；
- Token 平均值与标准差；
- 强制总结次数和比例；
- 格式修复次数、最终兜底次数和比例；
- 工具使用次数分布；
- 总耗时。

总体 Profile 标准差会同时受到案例难度和模型随机性影响。`case_summaries` 固定 Profile 和 Case，只比较同一道题的多次运行，更适合判断稳定性。一次运行的标准差为 0 仅表示没有足够样本，不能证明绝对稳定。

## 12. 测试

运行全部离线测试：

```powershell
.venv\Scripts\python.exe -m unittest discover -v
```

当前共有 198 项测试，覆盖：

- 完整 Benchmark 静态审计及 JSON 报告持久化；

- 模型服务能力配置；
- 工具注册、严格参数和统一错误；
- 严格 Tool Schema 的 `required == properties`、nullable 行号和非严格模式兼容；
- 路径越界、敏感配置和内部目录隔离；
- 文件、RAG 和 Git 工具；
- `read_file` 包含端点的定向读取、原始行号、30 行上限、反向范围拒绝和旧整文件调用兼容；
- 定向读取的紧凑 Observation 摘要会保留窗口末端关键行，压缩上下文不会再次把它截成 700 字符；普通 Observation 仍保持原上限；
- 同一文件单窗口或多个相邻成功窗口的联合覆盖检测、部分重叠新增行放行，以及失败读取不污染覆盖记录；
- Runtime/Harness 工具白名单、严格参数、固定 Runner、结构化超时、环境密钥隔离和无 Shell 执行；
- Harness 清单重复 ID、未知 ID、路径越界、内部评测目标与模型自带命令字段的拒绝；
- `unittest` 结果计数、失败用例提取、预期非零退出码和真实 Runtime Observation；
- `run_check` 人工审批、恢复执行、定义哈希绑定与幂等安全重放；
- Patch Proposal 必须显式开启，默认调查和 Evaluation 不增加调用；
- unified diff JSON 解析、文件头、hunk 行数与当前磁盘上下文匹配；
- 补丁 Claim、代码 Evidence、changed_files 和 Harness 检查 ID 绑定；
- 拒绝未取证文件、测试、Harness、Evaluation、配置、越界路径及创建/删除/重命名；
- 验证成功与失败的补丁都不会改变业务文件；
- `--verify-patch` 在临时副本应用补丁，正式目标文件前后字节保持一致；
- 补丁验证拒绝没有 `covers_files` 契约检查覆盖的修改文件；
- `reproduction` 基线必须先复现旧故障，补丁后必须正常退出；`regression` 补丁后必须保持预期；
- 模型漏选时仍自动加入覆盖检查和全局回归检查；
- ValueError 替换 KeyError 但没有按 API 契约返回 400 的补丁会被行为检查拒绝；
- 补丁验证批准、拒绝、持久化等待状态和恢复执行；
- Runtime 摘要优先保留异常消息与业务 traceback 帧，长堆栈不会挤掉根因线索；
- LangGraph 路由、报告重试、预算和强制总结；
- 内部假设工具的格式、ID、成功 Observation 与状态约束；
- 两项独立来源早停和单条证据不早停；
- 完整开放假设集合至少提供一个结构化下一步动作，同时允许其他开放候选暂不重复规划；
- 上下文压缩保留假设引用证据和最近未分类证据，并移除悬空 Tool 消息；
- 最终总结上下文保留所有具有来源的成功 Observation；
- 最终 Evidence 白名单按来源扁平展开，成功但无来源的 Observation 不会被误当成可引用证据；
- Provenance 修复必须从精确白名单整项替换错误来源，并删除未被 Claim 使用的 Evidence；
- 新证据未更新假设时阻止后续外部工具，更新完成后恢复调查；
- 没有新 Observation 时从模型 Schema 隐藏假设工具，并在执行层拒绝兼容服务返回的未声明重复更新；
- 连续两次无效假设更新触发受限总结，避免把全部模型预算耗在内部状态格式修复上；
- 最后一批成功 Observation 在硬调查预算结束后最多获得一次受限归类，且不增加调查步骤；
- 受限归类只能调用内部假设工具，外部工具请求会被执行层拒绝；不足三次模型额度时直接总结，保留格式修复机会；
- Prompt 明确区分 failure site 与系统根因，并要求检查上游调用方、入口校验和相关业务契约；
- JSON 代码块及前后说明文字解析、详细验证错误持久化；
- 最终格式修复失败时，从真实 Observation 构造有来源的降级报告；
- 空 Evidence 报告的引用有效率记为 0%，不再显示误导性的 100%；
- 单轮工具上限拦截并行铺开，但允许下一轮重新规划；
- 直到最后预算轮才确认的假设不会被误记为早停；
- LangGraph 原生 HITL interrupt、checkpoint 与 resume；
- Runtime 在执行前 interrupt，批准后恢复执行，拒绝后不启动进程；
- SQLite 会话在关闭并重新打开 Store 后仍能从原 interrupt 恢复；
- 当前终端可以处理审批并自动恢复，连续 interrupt 不要求用户重复复制调查 ID；
- `Ctrl+C` 或 EOF 不会误执行审批，等待状态仍可在新进程中恢复；
- V10 数据库自动增加 Memory 召回字段，不需要清空已有会话；
- `doctor` 在不联网的情况下检查依赖、配置、Harness 清单和 SQLite，且不会输出 API Key；
- 同一 Runtime `execution_id` 只执行一次，已完成时重放结果，不确定时拒绝重跑；
- API Key 不写入持久化 SQLite，`.incident_state` 不向 Agent 文件工具暴露；
- 只有正常完成且证据引用完整的 medium/high 报告才生成 `pending` Memory；
- pending/rejected Memory 不参与召回，approved Memory 才能按相似度进入新调查；
- 同一源调查不会重复生成候选，`forget` 会精确删除指定 Memory；
- 召回文本明确声明“历史不是证据”，且 `Evidence.source_type` 拒绝 `memory`；
- 持久化调查记录召回 ID 和数量，兼容 `run_agent()` 不读取或写入长期记忆；
- 超过三次真实调查的费用保护；
- 并行工具请求不能越过执行层硬预算，超额请求仍保留失败 Observation；
- 重复工具调用纠正窗口与二次重复保护；
- 强制总结失败后的单次无工具格式修复；
- Tool Profile Schema 过滤和执行层越权拒绝；
- 多行命令行输入；
- 十二个可执行 Demo 故障稳定复现，以及八个扩展案例的隔离参考修复验证；
- Profile 对 RAG 文档和外部系统夹具的路径级隔离；
- 文档得分必须由 `retrieve_docs` 调用触发；
- 精确错误码和配置键在混合检索中获得额外权重，供应商契约优先召回；
- 评分、引用验证和 JSON 保存；
- 带单位数值关键词和终端失败原因；
- Tool Observation 生成、ID 回传和来源范围提取；
- 伪造 Observation、越界行号和缺失 Evidence 拒绝；
- Git Commit 短哈希与真实 `git_log` Observation 绑定；
- Claim—Evidence Ledger 完整性与 Evidence 落地评分；
- Runtime ID 来源绑定和 `runtime_required` 硬通过条件；
- 多 Profile、多次运行、标准差和聚合输出；
- 旧 `run_agent()` 接口兼容。

离线测试使用模拟模型，不读取真实 API Key，不产生模型费用。真实 Evaluation 与消融实验只有在主动运行 `run_evals.py` 时才调用 `api.env` 配置的模型。

运行完整确定性审计：

```powershell
.\.venv\Scripts\python.exe benchmark.py
```

该命令不调用模型。它会检查十五个 Evaluation 的集合划分、可见证据与评分关键词、RAG 文档、日志、文件工具隔离、十二个复现入口与二十二个 Harness Check，并验证冻结基线原始报告的 SHA-256；默认还会以模块和脚本两种方式执行十二个故障入口、运行全部 Harness Check 和审计专项回归。结果写入 `demo_app/evals/results/v14.7-deterministic-audit.json`。如只需快速检查静态结构，可添加 `--skip-processes`。

审计状态允许 `passed_with_warnings`：这表示所有完整性检查均通过，但报告明确保留评分策略风险。当前已知两项是 `expected_exception` 尚未作为硬通过门槛，以及多 Evidence 文件案例的代码覆盖硬阈值仍为 50%。为保持冻结历史结果可比较，V14.7 只报告风险，不在同一阶段修改评分口径。

## 13. 安全设计

### 13.1 路径和敏感文件

- 所有文件路径解析后必须仍在项目根目录；
- `api.env`、`.env` 等敏感配置不可读取或搜索；
- `.git`、`.venv`、缓存、构建目录和依赖目录不会进入文件列表或代码搜索；
- `evals/`、评测实现、评测测试、`.incident_cache/`、`.incident_reports/` 和 `.incident_state/` 对 Agent 不可见；
- `git_diff` 只接受单个现有文件，不能用仓库根目录批量泄露隐藏内容；
- 二进制或非 UTF-8 文件不会作为文本发送给模型；
- 文件内容、搜索命中和目录项都有数量或长度限制。

### 13.2 调查与执行边界

文件、RAG、Git 和 `list_checks` 都是只读的。Runtime 工具会启动一个本地子进程，但模型只能选择预登记 ID，不能提供命令、路径、参数、工作目录或环境变量；清单 target 还会经过 Runner 专用校验。执行受默认关闭的环境开关、独立 Profile、交互式单次审批、调用次数、双重超时和持久幂等账本共同约束。V13 的补丁验证使用另一项审批，在批准前不创建临时副本；批准后只复制项目安全子集，排除密钥、Git、虚拟环境、缓存、报告、状态和符号链接，且只在该副本写入。正式目标文件在验证前后进行 SHA-256 对比。Git、Runtime 和补丁验证都不通过 Shell 拼接模型文本。Evaluation 在 `.incident_reports/` 写报告，RAG 在 `.incident_cache/` 写缓存，持久化 CLI 在 `.incident_state/` 写状态；这些属于本地基础设施，不是模型可调用的正式业务写入工具。

### 13.3 外部模型数据边界

文件和文档首先由本地工具读取，但工具结果会加入消息并发送给配置的模型服务。所谓“本地工具”不代表代码内容永远留在本机。不要用当前版本调查不允许发送给服务商的私有代码。

### 13.4 长期记忆与污染防护

- 新报告先成为 `pending` 候选，不会自动进入召回池；
- 只有用户明确批准的记录参与召回，拒绝项仍可审计，删除只作用于精确 Memory ID；
- 召回排序在本机完成，不会为了搜索历史额外调用模型；
- 历史内容进入提示词时带有非证据标记，不能获得 Observation ID；
- 最终 Evidence 的来源类型只允许代码、文档、Git 和 Runtime 等当前调查来源，不接受 `memory`；
- 即使历史根因与新问题高度相似，Agent 仍需读取当前来源重新建立证据链。

## 14. 如何提出高质量问题

最好提供：

1. 完整 traceback；
2. 实际运行命令；
3. 当前工作目录；
4. 预期行为；
5. 实际行为；
6. 最近是否修改依赖、配置、数据库或分支。

示例：

```text
我在项目根目录运行：
python -m demo_app.run_case schema_mismatch

最后出现：
sqlite3.OperationalError: table users has no column named user_id

预期是创建用户。请结合代码、项目文档和 Git 信息调查根因，给出文件与行号证据，不要修改代码。
```

只有 `Traceback (most recent call last):` 或单独一行源码通常不足以确定根因。当前版本尚未实现自动澄清节点，信息不足时仍可能进行过多调查。

## 15. 常见问题

### 找不到 `langgraph`

```text
ModuleNotFoundError: No module named 'langgraph'
```

请使用项目虚拟环境安装并运行：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

### 找不到 `demo_app`

推荐在项目根目录使用模块方式：

```powershell
.venv\Scripts\python.exe -m demo_app.run_case missing_user_id
```

`demo_app/run_case.py` 也兼容直接脚本启动。若 traceback 中导入语句仍在旧行号，可能运行的是修复前文件、未保存副本或另一个工作目录。

### 多行 traceback 被拆成多个问题

当前 `main.py` 已连续收集多行，并以空行提交。确认运行的是当前工作区的 `main.py`，粘贴结束后只额外按一次 Enter。

### Agent 调用了很多工具

一次模型响应可以同时提出多个工具调用，所以模型轮数和工具次数不同。系统默认每轮最多真正执行 3 个外部工具，超出的调用会收到 `per_step_tool_limit`；模型需要在下一轮按信息价值重排。已有假设并取得新证据后，模型还必须先通过 `update_hypotheses` 归类证据，否则新外部调用会被控制门拒绝。confirmed 假设获得两项独立来源后会提前总结。硬预算分别限制模型、工具和 Runtime 调用，交互模式达到软阈值或请求 Runtime 时暂停询问用户。当前去重仍只识别完全相同的工具名与参数，尚未识别语义相似调查。

### Evaluation 为什么提示费用保护

一次 Profile × 一个 Case × 一次重复等于一次完整 Agent 调查，而一次调查内部可能调用模型多次。当前最多免确认运行 3 次；更大的批量任务必须添加 `--yes`。建议先运行一个 Case 和一个 Profile，不要把 `--compare --runs 3 --yes` 当作烟雾测试。Runtime 评测还需要单独添加 `--allow-runtime`。

### Evaluation 为什么没有触发人工审查

`run_evals.py` 是无人值守、可重复的批量评测，默认调用 `run_agent_detailed(..., human_review=False)`；否则实验会等待键盘输入，而且不同人工选择会污染 Profile 对照。因此即使达到 HITL 软阈值，Evaluation 也不会暂停，但模型和工具硬预算仍然生效。Runtime 专项实验用命令行的 `--allow-runtime` 作为整次运行的显式预授权，并会把实际执行次数写入报告。

要验证人工审查，请运行交互入口：

```powershell
.\.venv\Scripts\python.exe main.py
```

默认在模型调用达到 5 次或工具调用达到 10 次时暂停。若只想演示流程，可暂时在 `api.env` 将两个 `HITL_*_THRESHOLD` 设为 1，验证后恢复默认值；如果 Agent 在阈值前已经取得充分证据并结束，则不触发人工确认是正确行为。

### 为什么没有看到 Runtime 批准提示

先确认 `api.env` 中是 `ENABLE_RUNTIME_TOOLS=true`，并且重启了 `main.py`。批准提示不是启动程序时固定出现，而是模型实际选择 `run_demo_case` 时才出现；问题里明确写“实际复现”更容易触发。若模型只靠静态证据结束，说明它没有请求执行。要确定性验证这项能力，请运行 `runtime_required + full_runtime + --allow-runtime` 专项 Evaluation，并检查 JSON 中 `runtime_call_count`、Runtime Observation 和最终 Evidence 的 `runtime_id`。

### Evaluation 答案正确但没有通过

当前根因评分仍然是字面关键词规则。正确同义表达可能造成假阴性。先查看 JSON 中缺失的具体关键词，不要只看总通过率。未来将使用同义概念组和 LLM Judge 做混合评测。

### 为什么现在通常不需要手动 resume

`main.py new` 收到 LangGraph interrupt 后会先确保 Checkpoint 已经写盘，然后直接在当前终端询问。你作出选择后，CLI 在内部发送 `Command(resume=...)` 并继续运行；即使连续出现 Runtime 审批和费用审查，也会在同一个命令中依次处理。只有按 `Ctrl+C`、输入流结束、终端意外关闭，或者主动使用 `new --detach` 时，调查才停在等待状态，此时再执行输出中的 `resume <调查ID>`。

### Checkpoint 在重启后丢失

如果使用无参数的 `main.py` 或直接调用 `run_agent()`，这条兼容路径仍是 `InMemorySaver`，退出后不保留。需要重启恢复时，从 `main.py new` 开始，再用 `list/show/resume` 管理调查。

### Runtime 审批后恢复时会不会执行两次

正常完成的相同 `execution_id` 只返回账本中的原结果，不启动第二次进程。如果机器在外部进程启动后、结果记录前崩溃，账本会保留 `running`；此时系统拒绝自动重跑，需要人工判断。这比盲目重试执行型操作更安全。

### 为什么完成调查后没有产生 Memory

只有通过持久化 `main.py new/resume` 完成的调查才会沉淀长期记忆，而且报告必须正常完成、置信度为 medium/high、同时包含 Claim 与 Evidence，并且所有 Claim 引用都能找到对应 Evidence。取消、失败、低置信度和引用不完整都不会生成候选。兼容入口 `main.py` 无参数模式和 `run_agent()` 有意不读写长期记忆。

### 为什么相似问题没有召回历史

先运行 `memory list --status pending`，确认候选是否还未审批；只有 `memory approve <memory_id>` 后才会进入召回池。召回采用本地词法匹配，问题中至少要有与历史异常类型、关键标识符、文件或根因摘要相关的词。可以先用 `memory search <关键词>` 检查本地排序结果。即使召回成功，它也只是调查提示，不会直接出现在最终 Evidence 中。

## 16. 当前限制

- Demo 只有十五个评测案例，规模仍然不能代表生产环境；
- Case、代码注释和事故文档比较明确，存在玩具数据集偏简单的问题；
- 根因关键词不理解同义词，也可能被关键词投机；
- Observation 能确认模型实际看过来源，但不能完全判断自然语言 Claim 与证据的语义蕴含关系；
- 当前没有 LLM-as-a-Judge；
- 已记录服务商返回的 Token，但尚未根据不同模型价格计算真实金额；服务商不返回 usage 时 Token 显示 0；
- 普通 Observation 只保存最多 1,000 字符结果摘要和 SHA-256；成功的定向 `read_file` 为避免末端代码丢失，会保存最多 4,000 字符的紧凑行号摘要。单行特别长时仍会按窗口行数缩短，完整工具内容主要保留在 LangGraph 消息状态中；
- 发给模型的压缩记忆将普通 Observation 摘要限制为 700 字符，定向文件窗口限制为 4,000 字符；普通调查只保留所有已引用证据和最近 4 条未引用结果，最终报告阶段则恢复全部带来源的成功结果。其他长结果中的次要细节仍可能被省略，但本地 Checkpoint 中的完整消息不会被删除；
- 上下文压缩的实际 Token 节省依赖模型服务是否返回 usage，必须通过同一 Case、同一模型的真实对照确认，离线测试不能证明具体节省比例；
- 语义重复检测当前只覆盖定向 `read_file` 的真实行范围；其他工具仍按规范化参数精确去重，新的整文件请求也不会根据不完整窗口推测文件末尾；
- 最后证据归类只有在总模型预算至少剩余三次请求时才执行；否则系统优先保证最终总结和一次格式修复，假设可能保持尚未归类状态；
- `confidence` 是模型自我声明，不是校准后的概率；
- 已有确定性假设 Gate，但“两个独立来源”是工程启发式，不等于自然语言语义蕴含证明；
- 跨进程 HITL 只在单机 SQLite CLI 路径提供；直接 `run_agent()` 仍是内存模式，也不会授权绕过评测和敏感路径隔离；
- SQLite 适合单机演示，尚无多用户身份、会话归属和分布式并发控制；
- 长期记忆当前是单机 SQLite 中的人工审批记录，没有用户级权限、过期策略和跨项目共享；
- Memory 召回使用可解释词法相似度，没有 Embedding、向量数据库或学习型重排；表达完全不同但语义相同的事故可能无法命中；
- 已批准的历史仍可能过时或错误，因此只能作为候选假设，必须在当前调查中重新取证；
- 外部子进程与 SQLite 不能组成单个原子事务；崩溃留下的 `running` Runtime 操作需要人工处理；
- Harness 只覆盖 `harness.json` 中预登记的本仓库检查，不是容器或通用沙箱；编辑清单等同于授予新的本地测试能力，必须由项目所有者审查；
- Runtime 批准按当前模型工具请求生效，默认预算只允许实际运行一次；尚未实现风险等级和审批策略引擎；
- Patch Proposal 目前只允许修改已取证的现有 `.py` 文件，最多 3 个文件和 120 行增删；不能创建文件，也不能同时生成测试修改；
- V13 的 `verified` 只证明候选补丁通过当前预登记检查，不能证明未覆盖行为、性能、并发或生产环境一定正确；
- 临时目录是工作区隔离，不是容器或操作系统安全沙箱；项目所有者必须审查 `harness.json`，因为已登记 Python 检查仍作为本机子进程运行；
- 临时副本主动排除密钥和状态，但当前没有操作系统级文件系统与网络隔离；只应登记可信的项目检查；
- 每个修改文件必须已有 `covers_files` 覆盖声明，因此没有对应契约检查的文件会被拒绝验证，需要项目所有者先补充可信检查；
- 补丁生成只有一次模型机会；格式或 hunk 上下文错误时直接保留为 `rejected`，不会为了修复格式自动增加第二次调用；
- 验证通过的补丁不会自动写回正式工作区；尚无正式应用审批、提交、自动回滚或 PR 流程；
- 没有 Web UI 或服务端 API。
- `requirements.lock` 只锁定五个直接依赖，没有像完整锁文件工具那样记录所有传递依赖和平台哈希。

## 17. 后续规划

推荐顺序：

1. 保留已经冻结的 V13 与 V14.3 五案例正式对照；修复后的 `retry_non_idempotent` 单案例验收只作为来源合约的补充证据，不回写或重算正式 3/5 快照；
2. Expanded Benchmark 已达到十二个可执行场景；十五个 Evaluation 的划分、复现、Harness、文档索引、答案隔离、关键词来源和冻结结果哈希已纳入 V14.7 完整确定性审计；
3. 下一阶段加入默认关闭、每份报告只调用一次的 LLM Judge，用于识别 `async_missing_await` 这类语义正确但词法未命中的报告，同时不替代本地引用真实性判断；
4. 最后补充命令行产品演示；若进入自动修复产品阶段，再单独设计正式工作区应用审批、Git 分支/提交、回滚和容器级执行隔离。

系统把可持久的 Human-in-the-loop 放在每个执行型 Runtime 工具之前，把另一类人工审批用于长期知识进入召回池之前，并为 V13 临时补丁写入建立了独立审批门。未来若允许写入正式工作区，还必须新增更高权限的应用审批，不能把“允许临时验证”解释成“允许修改源码”。

## 18. 面试讲解版本

一句话：

> IncidentPilot 是一个基于 LangGraph 的成本感知、假设与证据驱动 Python 故障诊断 Agent。它用结构化下一步动作和单轮工具上限控制调查宽度，用压缩调查记忆降低重复输入 Token；只有 confirmed 假设获得独立 Observation 才提前总结。Safe Test Harness 让模型只能选择人工预登记的检查 ID，由系统构造固定 Runner 命令；执行前由 interrupt 请求批准，SQLite Checkpoint 支持跨进程恢复，定义哈希和幂等账本避免误用旧结果或重复执行。V13 用严格 Schema 与 Observation 白名单约束报告和候选 diff，再经独立审批在临时副本做补丁前复现、补丁后契约与回归验证，正式工作区始终不变。

完整流程：

> 用户提交完整 traceback 后，持久化入口先在本地召回最多三条已审批相似事故，并明确标为非证据线索。模型通过内部控制工具保存候选 Hypothesis，为未确认假设声明可证伪的下一步动作，每轮只执行有限数量的高信息价值工具；完整状态留在 Checkpoint，而模型请求只携带当前假设、被引用证据和最近未分类证据。若需要真实复现，模型先用 `list_checks` 发现能力，再用 `run_check(check_id)` 请求固定检查并进入 `runtime_review`，SQLite Checkpoint 在执行前同步持久化 interrupt；用户批准后，系统从受信清单构造 Runner 参数，幂等账本再决定是真正执行、返回旧结果还是因结果不确定而拒绝重跑。系统拒绝不存在、失败、伪造或来自历史 Memory 的 Evidence；confirmed 假设必须获得至少两项独立来源才触发早停。最终 Claim—Evidence Ledger 经过 Pydantic 和 Provenance 双重验证，合格报告才生成待审批 Memory；如果调用方显式请求补丁，Graph 再进行一次无工具模型调用生成草稿，本地校验 Claim、文件、hunk 上下文与 Harness ID。若请求 V13 验证，Graph 在独立审批后把项目复制到临时目录，先验证原故障可复现，再应用 diff，最后自动运行覆盖修改文件的契约检查和全局回归，清理副本并确认正式源码未变。Evaluation 同时衡量准确性、证据落地、Runtime 使用、历史召回、上下文压缩、Token、工具贡献和稳定性。

## 19. 文档维护规则

以后每次升级版本必须同步维护：

- `README.md`：只保留新版本当前真实存在的完整说明，更新版本号、结构、命令、数据流、限制、测试数量和后续规划；
- `CHANGELOG.md`：新增该版本的“新增、修改、修复、安全、验证和兼容性”记录。

不要再把旧版本实现说明连续追加到 README。历史原因、迁移过程和版本差异统一放入 CHANGELOG；当前使用者只需要阅读 README。
